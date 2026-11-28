import { defineStore } from 'pinia'
import { computed, ref, toRaw, watch } from 'vue'

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
import { DECISIONS } from '@/utils/decisions'

import { useUiStore } from './ui'

const PREFETCH_AHEAD = 8
/**
 * A decision not answered by then is taken back: one hanging request would otherwise hold every write after it, and
 * the reloads waiting for them.
 */
const WRITE_OPTS = { timeoutMs: 15_000 }
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
  /** A card is flying away or back on screen: an undo waits until it has landed. */
  const moving = ref(false)

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

  /** Set when the server turned a decision down because the queue is being applied (from another screen). */
  const applyRunning = ref(false)

  function onRefused(err: unknown) {
    if (err instanceof ApiError && err.type === 'apply_job_running') applyRunning.value = true
    report(err)
  }

  /**
   * Bumped by `clear()` (another account took over): an answer to a request made before it is the last account's,
   * and must not land in the deck of the new one.
   */
  let generation = 0

  /**
   * Decisions and undos reach the server one at a time, in the order made: an undo can't overtake the decision it
   * takes back, and the last answer of a burst counts every decision in it. Meanwhile the counts move locally.
   */
  let writes: Promise<unknown> = Promise.resolve()
  let writing = 0
  /** Writes started so far: a list read while one was sent is older than the deck on screen. */
  let wrote = 0

  async function write(send: () => Promise<{ counts: DeckCounts }>) {
    const asked = generation
    writing += 1
    wrote += 1
    const turn = writes.then(send)
    writes = turn.catch(() => undefined)
    try {
      const res = await turn
      // An earlier answer knows nothing of the decisions still queued behind it
      if (writing === 1 && asked === generation) counts.value = res.counts
    } catch (err) {
      // The last of a burst turned down: no answer brought the server's counts, and the local ones can't know
      // everything it does (a changed mute that was applied already is pending again)
      if (writing === 1 && asked === generation) void refreshCounts()
      throw err
    } finally {
      writing -= 1
    }
  }

  function listParams() {
    return new URLSearchParams({
      kind: kind.value,
      role: role.value,
      archive: prefs.value.archive,
      sort: prefs.value.sort,
      reverse: String(prefs.value.reverse),
    })
  }

  /** The server's counts, the list itself left as it is. */
  async function refreshCounts() {
    const asked = generation
    const seen = wrote
    try {
      const data = await api.get<ChannelsResponse>(`/api/channels?${listParams()}`)
      // A decision made meanwhile isn't in them; a reload brings its own
      if (asked === generation && seen === wrote && !writing && !loading.value)
        counts.value = data.counts
    } catch {
      /* the next decision's answer brings them */
    }
  }

  async function loadPrefs() {
    const asked = generation
    try {
      const loadedPrefs = await api.get<Prefs>('/api/prefs')
      if (asked === generation) prefs.value = loadedPrefs
    } catch {
      /* defaults are fine */
    }
  }

  /** Bumped by every `load()`: only the latest one's answer lands (a sort switched twice, a sync done meanwhile). */
  let loads = 0

  async function load() {
    const asked = generation
    const ticket = ++loads
    loading.value = true
    try {
      if (!loaded.value) await loadPrefs()
      // Decisions still on their way first: a list read before them would bring their cards back
      await writes
      const seen = wrote
      const params = listParams()
      const trailParams = new URLSearchParams({
        kind: kind.value,
        role: role.value,
        archive: prefs.value.archive,
      })
      const [data, decided] = await Promise.all([
        api.get<ChannelsResponse>(`/api/channels?${params}`),
        api.get<{ items: Channel[] }>(`/api/decisions/trail?${trailParams}`),
      ])
      // the user switched again while this was loading (the deck, its order, or the account)
      if (asked !== generation || ticket !== loads) return
      // A decision was made while it was read: the list may not have it, so read it again
      if (seen !== wrote) return await load()
      queue.value = data.items
      trail.value = decided.items
      cursor.value = null
      counts.value = data.counts
      sync.value = data.sync
      loaded.value = true
    } catch (err) {
      if (ticket === loads) report(err)
    } finally {
      if (ticket === loads) loading.value = false
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

  /** Moves the counts by a decision made (1) or taken back (-1), as the server will once it hears of it. */
  function tally(decision: Decision, sign: 1 | -1) {
    if (decision === 'skip') return
    const c = counts.value
    c.undecided -= sign
    c.by_decision[decision] += sign
    if (DECISIONS[decision].applied) c.pending += sign
  }

  /** The progress bar's letters, from the trail as it is now. */
  function retrace() {
    counts.value.trail = trail.value
      .map((c) => (c.decision ? (DECISIONS[c.decision].code ?? '') : ''))
      .join('')
  }

  function advance() {
    if (cursor.value === null) return
    cursor.value = cursor.value + 1 < trail.value.length ? cursor.value + 1 : null
  }

  /**
   * `channelId`: the card the swipe started on. By the time it has flown away the deck may have moved (a sync's
   * reload, an undo from the summary), and the decision must still go to that card, not to whichever is on top.
   */
  async function decide(decision: Decision, extra: DecisionExtra = {}, channelId?: number) {
    returning.value = null
    const id = channelId ?? current.value?.id
    if (id === undefined) return
    const decidedAt = trail.value.findIndex((c) => c.id === id)
    if (decidedAt >= 0) {
      // Rewound to it; it moved on in the trail meanwhile only if the deck was reloaded under the swipe
      if (cursor.value === null) return
      return revise(decidedAt, decision, extra, decidedAt === cursor.value)
    }
    const at = queue.value.findIndex((c) => c.id === id)
    if (at < 0) return // gone from the deck while it flew
    const [channel] = queue.value.splice(at, 1) as [Channel]
    if (decision === 'skip') queue.value.push(channel)
    else trail.value.push({ ...channel, decision, successor_id: extra.successor_id ?? null })
    const entry: HistoryEntry = { channel, decision }
    history.value.push(entry)
    tally(decision, 1)
    retrace()
    if (decision !== 'skip') stamps.value.push(Date.now())
    try {
      await write(() => api.put(`/api/decisions/${id}`, { decision, ...extra }, WRITE_OPTS))
    } catch (err) {
      // Taken out by what it is, not by position: later decisions may have come after it meanwhile
      history.value = history.value.filter((h) => toRaw(h) !== entry)
      queue.value = queue.value.filter((c) => c.id !== id)
      trail.value = trail.value.filter((c) => c.id !== id)
      queue.value.unshift(channel)
      tally(decision, -1)
      retrace()
      onRefused(err)
    }
  }

  /** Change a decision made earlier, in place; `moveOn`: to the next one, as for the card on top. */
  async function revise(
    index: number,
    decision: Decision,
    extra: DecisionExtra = {},
    moveOn = true,
  ) {
    const channel = trail.value[index]
    if (!channel) return
    const previous = channel.decision ?? 'keep'
    // While rewinding, "later" means "leave this one as it is".
    if (decision === 'skip' || decision === previous) return moveOn ? advance() : undefined
    trail.value[index] = { ...channel, decision, successor_id: extra.successor_id ?? null }
    tally(previous, -1)
    tally(decision, 1)
    retrace()
    const entry: HistoryEntry = { channel, decision, previous, index }
    history.value.push(entry)
    if (moveOn) advance()
    try {
      await write(() => api.put(`/api/decisions/${channel.id}`, { decision, ...extra }, WRITE_OPTS))
    } catch (err) {
      history.value = history.value.filter((h) => toRaw(h) !== entry)
      const at = trail.value.findIndex((c) => c.id === channel.id)
      if (at >= 0) {
        trail.value[at] = channel
        if (moveOn) cursor.value = at
      }
      tally(decision, -1)
      tally(previous, 1)
      retrace()
      onRefused(err)
    }
  }

  /**
   * Takes the last decision back. The card comes back at once, as a decision leaves at once: waiting for the
   * server first was a pause you could see on a phone. A refusal puts everything where it was.
   */
  async function undo() {
    // A card on its way out: its decision isn't in the history yet, and an undo now would take the one before
    if (moving.value) return
    const entry = history.value.pop()
    if (!entry) return
    const id = entry.channel.id
    const cursorBefore = cursor.value
    // A changed decision goes back to what it was, and the card comes back on top. Found by id: a reload since
    // may have changed the trail's order
    if (entry.previous !== undefined) {
      const previous = entry.previous
      const index = trail.value.findIndex((c) => c.id === id)
      const changed = trail.value[index]
      if (!changed) return
      trail.value[index] = { ...entry.channel, decision: previous }
      tally(entry.decision, -1)
      tally(previous, 1)
      retrace()
      cursor.value = index
      returning.value = entry
      try {
        // A transfer goes back to the same successor
        const successor = previous === 'transfer' ? entry.channel.successor_id : null
        await write(() =>
          api.put(
            `/api/decisions/${id}`,
            { decision: previous, ...(successor ? { successor_id: successor } : {}) },
            WRITE_OPTS,
          ),
        )
      } catch (err) {
        const at = trail.value.findIndex((c) => c.id === id)
        if (at >= 0) trail.value[at] = changed
        tally(previous, -1)
        tally(entry.decision, 1)
        retrace()
        cursor.value = cursorBefore
        history.value.push(entry)
        onRefused(err)
      }
      return
    }
    const skippedAt = entry.decision === 'skip' ? queue.value.findIndex((c) => c.id === id) : -1
    const trailAt = entry.decision === 'skip' ? -1 : trail.value.findIndex((c) => c.id === id)
    // What a refusal puts back: the very items, decision and all
    const skipped = queue.value[skippedAt]
    const decided = trail.value[trailAt]
    if (skippedAt >= 0) queue.value.splice(skippedAt, 1)
    if (trailAt >= 0) trail.value = trail.value.filter((c) => c.id !== id)
    cursor.value = null
    queue.value.unshift({ ...entry.channel, decision: null })
    tally(entry.decision, -1)
    retrace()
    returning.value = entry
    try {
      await write(() => api.del(`/api/decisions/${id}`, WRITE_OPTS))
    } catch (err) {
      const back = queue.value.findIndex((c) => c.id === id)
      if (back >= 0) queue.value.splice(back, 1)
      if (skipped) queue.value.splice(skippedAt, 0, skipped)
      if (decided) trail.value.splice(trailAt, 0, decided)
      tally(entry.decision, 1)
      retrace()
      cursor.value = cursorBefore
      history.value.push(entry)
      onRefused(err)
    }
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

  /** A card found by search goes on top: a decided one is rewound to, an undecided one jumps the queue. */
  function bringToTop(channelId: number) {
    const decided = trail.value.findIndex((c) => c.id === channelId)
    if (decided >= 0) return jumpTo(decided)
    const index = queue.value.findIndex((c) => c.id === channelId)
    if (index < 0) return
    toEnd()
    const [channel] = queue.value.splice(index, 1)
    queue.value.unshift(channel!)
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

  /**
   * Who could take over each chat the user owns: loaded when its card comes up, `null` when it failed. A failure is
   * asked again the next time (the card comes up again, the picker opens): it may have been only the connection.
   */
  const admins = ref<Record<number, ChatAdmin[] | null>>({})
  const askingAdmins = new Set<number>()

  async function loadAdmins(channelId: number) {
    if (admins.value[channelId] || askingAdmins.has(channelId)) return
    askingAdmins.add(channelId)
    try {
      const res = await api.get<{ items: ChatAdmin[] }>(`/api/channels/${channelId}/admins`)
      admins.value[channelId] = res.items
    } catch {
      admins.value[channelId] = null
    } finally {
      askingAdmins.delete(channelId)
    }
  }

  function clear() {
    generation += 1
    queue.value = []
    trail.value = []
    cursor.value = null
    history.value = []
    loaded.value = false
    returning.value = null
    moving.value = false
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
    moving,
    applyRunning,
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
    bringToTop,
    forget,
    watchSync,
    unwatchSync,
    resync,
    reset,
    clear,
  }
})
