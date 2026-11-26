import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'

import { api, ApiError, subscribe } from '@/api/client'
import type {
  ArchiveFilter,
  Channel,
  ChatAdmin,
  ChatKind,
  RoleFilter,
  ChannelsResponse,
  Decision,
  DeckCounts,
  Prefs,
  SortMode,
  SyncState,
} from '@/api/types'
import { i18n } from '@/i18n'

import { useUiStore } from './ui'

const PREFETCH_AHEAD = 8
const KIND_KEY = 'cc.kind'
const ROLE_KEY = 'cc.role'

function readRole(): RoleFilter {
  try {
    return localStorage.getItem(ROLE_KEY) === 'managed' ? 'managed' : 'member'
  } catch {
    return 'member'
  }
}

function readKind(): ChatKind {
  try {
    return localStorage.getItem(KIND_KEY) === 'supergroup' ? 'supergroup' : 'channel'
  } catch {
    return 'channel'
  }
}
const ACTIONS: Decision[] = ['unsubscribe', 'mute', 'archive', 'transfer', 'delete', 'free_link']
const TRAIL_CODE = {
  keep: 'k',
  unsubscribe: 'u',
  mute: 'm',
  archive: 'a',
  transfer: 't',
  delete: 'd',
  free_link: 'l',
} as const

/** What a decision may carry besides itself: who gets the chat on a transfer. */
export interface DecisionExtra {
  successor_id?: number
}

export interface HistoryEntry {
  channel: Channel
  decision: Decision
  /** Set when an earlier decision was changed while rewinding: what it was before. */
  previous?: Decision
  /** Position of that decision in the trail. */
  index?: number
}

export const useDeckStore = defineStore('deck', () => {
  const ui = useUiStore()

  const kind = ref<ChatKind>(readKind())
  const role = ref<RoleFilter>(readRole())
  const queue = ref<Channel[]>([])
  /** Decided channels in the order decided — the progress bar, card by card. */
  const trail = ref<Channel[]>([])
  /** While rewinding: which decision of the trail is on top of the deck; null = at the end. */
  const cursor = ref<number | null>(null)
  /** What the deck shows: the rest of the trail from the cursor on, then the undecided. */
  const items = computed(() =>
    cursor.value === null ? queue.value : [...trail.value.slice(cursor.value), ...queue.value],
  )
  const rewinding = computed(() => cursor.value !== null)
  const history = ref<HistoryEntry[]>([])
  const counts = ref<DeckCounts>({
    total: 0,
    kind_totals: { channel: 0, supergroup: 0 },
    role_totals: { member: { channel: 0, supergroup: 0 }, managed: { channel: 0, supergroup: 0 } },
    archive_totals: { all: 0, active: 0, archived: 0 },
    undecided: 0,
    pending: 0,
    pending_other: 0,
    by_decision: {
      keep: 0,
      unsubscribe: 0,
      mute: 0,
      archive: 0,
      transfer: 0,
      delete: 0,
      free_link: 0,
    },
    trail: '',
  })
  const sync = ref<SyncState | null>(null)
  const prefs = ref<Prefs>({ sort: 'dead', reverse: false, archive: 'all' })
  const loaded = ref(false)
  const loading = ref(false)
  /** Set right after undo so the card can animate back in from where it left. */
  const returning = ref<HistoryEntry | null>(null)

  /** "+1" chips on their way to the progress bar; the bar waits for them to land. */
  const chipsInFlight = ref(0)
  /** Bumped when a chip lands, so the progress counter can pulse. */
  const landed = ref(0)
  /** Timestamps of this session's decisions, for the ETA. */
  const stamps = ref<number[]>([])

  const current = computed(() => items.value[0] ?? null)
  const decided = computed(() => counts.value.total - counts.value.undecided)

  /** Remaining time at the user's own pace (median gap between the last decisions), minutes. */
  const eta = computed(() => {
    const s = stamps.value
    if (s.length < 4) return null
    const gaps = s
      .slice(-11)
      .map((ts, i, arr) => (i ? ts - arr[i - 1]! : 0))
      .slice(1)
      .sort((a, b) => a - b)
    const median = Math.min(gaps[Math.floor(gaps.length / 2)]!, 30_000)
    return Math.round((median * counts.value.undecided) / 60_000)
  })
  const position = computed(() =>
    Math.min(counts.value.total - counts.value.undecided + 1, counts.value.total),
  )
  const syncing = computed(() => sync.value?.running ?? false)

  let stopSync: (() => void) | null = null
  const inflight = new Set<number>()

  function report(err: unknown) {
    const msg = err instanceof Error ? err.message : String(err)
    ui.toast(i18n.global.t('login.errors.generic', { msg }))
  }

  async function loadPrefs() {
    try {
      prefs.value = await api.get<Prefs>('/api/prefs')
    } catch {
      /* defaults are fine */
    }
  }

  async function load() {
    loading.value = true
    try {
      if (!loaded.value) await loadPrefs()
      const requested = kind.value
      const requestedRole = role.value
      const requestedArchive = prefs.value.archive
      const params = new URLSearchParams({
        kind: requested,
        role: requestedRole,
        archive: requestedArchive,
        sort: prefs.value.sort,
        reverse: String(prefs.value.reverse),
      })
      const [data, decided] = await Promise.all([
        api.get<ChannelsResponse>(`/api/channels?${params}`),
        api.get<{ items: Channel[] }>(
          `/api/decisions/trail?kind=${requested}&role=${requestedRole}&archive=${requestedArchive}`,
        ),
      ])
      // the user switched again while this was loading
      if (
        requested !== kind.value ||
        requestedRole !== role.value ||
        requestedArchive !== prefs.value.archive
      )
        return
      queue.value = data.items
      trail.value = decided.items
      cursor.value = null
      counts.value = data.counts
      sync.value = data.sync
      loaded.value = true
    } catch (err) {
      report(err)
    } finally {
      loading.value = false
    }
  }

  async function savePrefs(next: Prefs) {
    prefs.value = next
    try {
      await api.put('/api/prefs', next)
    } catch {
      /* not critical */
    }
    await load()
  }

  async function setKind(next: ChatKind) {
    if (next === kind.value) return
    kind.value = next
    try {
      localStorage.setItem(KIND_KEY, next)
    } catch {
      /* not critical */
    }
    // The undo history and the rewind position belong to the deck that was on screen
    history.value = []
    returning.value = null
    await load()
  }

  async function setRole(next: RoleFilter) {
    if (next === role.value) return
    role.value = next
    try {
      localStorage.setItem(ROLE_KEY, next)
    } catch {
      /* not critical */
    }
    history.value = []
    returning.value = null
    await load()
  }

  /** Several prefs at once (the settings menu's reset); one reload. */
  async function setPrefs(next: Prefs) {
    if (next.archive !== prefs.value.archive) {
      history.value = []
      returning.value = null
    }
    await savePrefs(next)
  }
  const setSort = (sort: SortMode) => savePrefs({ ...prefs.value, sort })
  async function setArchive(archive: ArchiveFilter) {
    if (archive === prefs.value.archive) return
    // The undo history and the rewind position belong to the list that was on screen
    history.value = []
    returning.value = null
    await savePrefs({ ...prefs.value, archive })
  }
  const toggleReverse = () => savePrefs({ ...prefs.value, reverse: !prefs.value.reverse })

  function snapshot(): DeckCounts {
    return { ...counts.value, by_decision: { ...counts.value.by_decision } }
  }

  function advance() {
    if (cursor.value === null) return
    cursor.value = cursor.value + 1 < trail.value.length ? cursor.value + 1 : null
  }

  async function decide(decision: Decision, extra: DecisionExtra = {}) {
    returning.value = null
    if (cursor.value !== null) return revise(cursor.value, decision, extra)
    const channel = queue.value.shift()
    if (!channel) return
    if (decision === 'skip') queue.value.push(channel)
    else trail.value.push({ ...channel, decision, successor_id: extra.successor_id ?? null })
    history.value.push({ channel, decision })
    const before = snapshot()
    if (decision !== 'skip') {
      counts.value.undecided -= 1
      counts.value.by_decision[decision] += 1
      counts.value.trail += TRAIL_CODE[decision]
      if (ACTIONS.includes(decision)) counts.value.pending += 1
      stamps.value.push(Date.now())
    }
    try {
      const res = await api.put<{ counts: DeckCounts }>(`/api/decisions/${channel.id}`, {
        decision,
        ...extra,
      })
      counts.value = res.counts
    } catch (err) {
      history.value.pop()
      if (decision === 'skip') queue.value.pop()
      else trail.value.pop()
      queue.value.unshift(channel)
      counts.value = before
      report(err)
    }
  }

  /** Change a decision made earlier, in place, and move on to the next one. */
  async function revise(index: number, decision: Decision, extra: DecisionExtra = {}) {
    const channel = trail.value[index]
    if (!channel) return
    const previous = channel.decision ?? 'keep'
    // While rewinding, "later" means "leave this one as it is".
    if (decision === 'skip' || decision === previous) return advance()
    const before = snapshot()
    trail.value[index] = { ...channel, decision, successor_id: extra.successor_id ?? null }
    counts.value.trail =
      counts.value.trail.slice(0, index) +
      TRAIL_CODE[decision] +
      counts.value.trail.slice(index + 1)
    history.value.push({ channel, decision, previous, index })
    advance()
    try {
      const res = await api.put<{ counts: DeckCounts }>(`/api/decisions/${channel.id}`, {
        decision,
        ...extra,
      })
      counts.value = res.counts
    } catch (err) {
      history.value.pop()
      trail.value[index] = channel
      cursor.value = index
      counts.value = before
      report(err)
    }
  }

  async function undo() {
    const entry = history.value.pop()
    if (!entry) return
    // A changed decision goes back to what it was, and the card comes back on top.
    if (entry.previous !== undefined && entry.index !== undefined) {
      try {
        // A transfer goes back to the same successor
        const successor = entry.previous === 'transfer' ? entry.channel.successor_id : null
        const res = await api.put<{ counts: DeckCounts }>(`/api/decisions/${entry.channel.id}`, {
          decision: entry.previous,
          ...(successor ? { successor_id: successor } : {}),
        })
        counts.value = res.counts
      } catch (err) {
        history.value.push(entry)
        report(err)
        return
      }
      trail.value[entry.index] = { ...entry.channel, decision: entry.previous }
      cursor.value = entry.index
      returning.value = entry
      return
    }
    try {
      const res = await api.del<{ counts: DeckCounts }>(`/api/decisions/${entry.channel.id}`)
      counts.value = res.counts
    } catch (err) {
      history.value.push(entry)
      report(err)
      return
    }
    if (entry.decision === 'skip') {
      const idx = queue.value.findIndex((c) => c.id === entry.channel.id)
      if (idx >= 0) queue.value.splice(idx, 1)
    } else {
      trail.value = trail.value.filter((c) => c.id !== entry.channel.id)
    }
    cursor.value = null
    queue.value.unshift({ ...entry.channel, decision: null })
    returning.value = entry
  }

  /** One card back (Ctrl+←): the previous decision comes back on top. */
  function stepBack() {
    const target = (cursor.value ?? trail.value.length) - 1
    const channel = trail.value[target]
    if (!channel) return
    cursor.value = target
    returning.value = { channel, decision: channel.decision ?? 'keep' }
  }

  /** One card forward (Ctrl+→), back to the undecided after the last one. */
  function stepForward() {
    returning.value = null
    advance()
  }

  function jumpTo(index: number) {
    returning.value = null
    cursor.value = index >= 0 && index < trail.value.length ? index : null
  }

  function toEnd() {
    returning.value = null
    cursor.value = null
  }

  function forget(channelId: number) {
    history.value = history.value.filter((h) => h.channel.id !== channelId)
  }

  /** Card info still to fetch: a refusal (full_error) is an answer too; rows cached before the pulse need it. */
  function needsInfo(channel: Channel) {
    return !(channel.full_loaded && (channel.pulse || channel.full_error))
  }

  /** Fetches one card's info; false when Telegram asked to wait, which holds for every card. */
  async function prefetch(channel: Channel): Promise<boolean> {
    if (!needsInfo(channel) || inflight.has(channel.id)) return true
    inflight.add(channel.id)
    try {
      const full = await api.get<Channel>(`/api/channels/${channel.id}/full`)
      // Keep the decision the deck knows about: the server copy may be older.
      for (const list of [queue.value, trail.value]) {
        const idx = list.findIndex((c) => c.id === channel.id)
        if (idx >= 0) list[idx] = { ...full, decision: list[idx]!.decision }
      }
    } catch (err) {
      if (err instanceof ApiError && err.type === 'flood_wait') {
        pauseUntil(Date.now() + (err.retryAfter ?? 10) * 1000)
        return false
      }
      // Anything else (no connection…): asked again when the deck moves
    } finally {
      inflight.delete(channel.id)
    }
    return true
  }

  // A flood wait pauses the whole prefetch: the next cards would only get the same answer, and Telegram lengthens
  // the wait for asking anyway. The cards show without their extras meanwhile.
  let pausedUntil = 0
  let resumeTimer: ReturnType<typeof setTimeout> | null = null
  let prefetching = false
  let again = false

  function pauseUntil(until: number) {
    pausedUntil = Math.max(pausedUntil, until)
    if (resumeTimer) clearTimeout(resumeTimer)
    resumeTimer = setTimeout(() => {
      resumeTimer = null
      void prefetchAhead()
    }, pausedUntil - Date.now())
  }

  async function prefetchAhead() {
    if (Date.now() < pausedUntil) return
    if (prefetching) {
      again = true // the deck moved meanwhile: one more round once this one is done
      return
    }
    prefetching = true
    try {
      do {
        again = false
        for (const channel of items.value.slice(0, PREFETCH_AHEAD)) {
          // sequential: the backend serialises GetFullChannel anyway
          if (!(await prefetch(channel))) return
        }
      } while (again)
    } finally {
      prefetching = false
    }
  }

  watch(
    () => items.value.slice(0, PREFETCH_AHEAD).map((c) => c.id),
    () => void prefetchAhead(),
  )

  function watchSync() {
    if (stopSync) return
    stopSync = subscribe('/api/channels/sync/events', {
      snapshot: (s: SyncState) => (sync.value = s),
      progress: (s: SyncState) => (sync.value = s),
      flood_wait: (s: SyncState) => (sync.value = s),
      error: (s: SyncState) => (sync.value = s),
      done: (s: SyncState) => {
        sync.value = s
        void load()
      },
    })
  }

  function unwatchSync() {
    stopSync?.()
    stopSync = null
  }

  async function resync() {
    try {
      sync.value = await api.post<SyncState>('/api/channels/sync')
    } catch (err) {
      report(err)
    }
  }

  async function reset(only: Decision | null) {
    try {
      await api.post('/api/decisions/reset', { only, kind: kind.value, role: role.value })
      history.value = []
      await load()
    } catch (err) {
      report(err)
    }
  }

  /** Who could take over each chat the user owns: loaded when its card comes up, `null` when Telegram said no. */
  const admins = ref<Record<number, ChatAdmin[] | null>>({})

  async function loadAdmins(channelId: number) {
    if (channelId in admins.value) return
    try {
      const res = await api.get<{ items: ChatAdmin[] }>(`/api/channels/${channelId}/admins`)
      admins.value[channelId] = res.items
    } catch {
      admins.value[channelId] = null
    }
  }

  function clear() {
    queue.value = []
    trail.value = []
    cursor.value = null
    history.value = []
    loaded.value = false
    returning.value = null
    admins.value = {}
    pausedUntil = 0
    if (resumeTimer) clearTimeout(resumeTimer)
    resumeTimer = null
  }

  return {
    kind,
    role,
    items,
    trail,
    cursor,
    rewinding,
    history,
    counts,
    sync,
    prefs,
    loaded,
    loading,
    returning,
    chipsInFlight,
    landed,
    current,
    decided,
    eta,
    position,
    syncing,
    admins,
    loadAdmins,
    load,
    setKind,
    setRole,
    setArchive,
    setPrefs,
    setSort,
    toggleReverse,
    decide,
    undo,
    stepBack,
    stepForward,
    jumpTo,
    toEnd,
    forget,
    watchSync,
    unwatchSync,
    resync,
    reset,
    clear,
  }
})
