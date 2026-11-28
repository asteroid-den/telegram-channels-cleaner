<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import { api } from '@/api/client'
import type { Channel, Decision } from '@/api/types'
import AppIcon, { type IconName } from '@/components/AppIcon.vue'
import ChannelAvatar from '@/components/ChannelAvatar.vue'
import { useHotkeys } from '@/composables/useHotkeys'
import { useApplyStore } from '@/stores/apply'
import { useDeckStore } from '@/stores/deck'
import { useUiStore } from '@/stores/ui'
import { actionErrorKind, errorText } from '@/utils/errors'
import { relativeTime } from '@/utils/format'

const { t, locale } = useI18n()
const router = useRouter()
const deck = useDeckStore()
const apply = useApplyStore()
const ui = useUiStore()

const pending = ref<Channel[]>([])
const failed = ref<Channel[]>([])
const loading = ref(true)
/** Why the queue couldn't be read: shown instead of an empty queue, which it isn't. */
const loadError = ref<string | null>(null)
const starting = ref(false)

const GROUPS: {
  decision: Decision
  icon: IconName
  label: string
  cls: string
}[] = [
  {
    decision: 'free_link',
    icon: 'link',
    label: 'review.freeLink',
    cls: 'bg-accent-soft text-accent',
  },
  {
    decision: 'unsubscribe',
    icon: 'x',
    label: 'review.unsubscribe',
    cls: 'bg-danger-soft text-danger',
  },
  { decision: 'mute', icon: 'bellOff', label: 'review.mute', cls: 'bg-warn-soft text-warn' },
  {
    decision: 'archive',
    icon: 'archive',
    label: 'review.archive',
    cls: 'bg-accent-soft text-accent',
  },
  // "keep" only shows up here when it takes back a mute/archive applied earlier
  { decision: 'keep', icon: 'undo', label: 'review.revert', cls: 'bg-surface-3 text-muted' },
]

const grouped = computed(() =>
  GROUPS.map((g) => ({
    ...g,
    // Leaving a chat the user owns has a block of its own, above
    items: pending.value.filter((c) => c.decision === g.decision && !ownedLeave(c)),
  })).filter((g) => g.items.length),
)

const ownedLeave = (c: Channel) => c.decision === 'unsubscribe' && c.role === 'owner'
const transfers = computed(() => pending.value.filter((c) => c.decision === 'transfer'))
const leavingOwnedList = computed(() => pending.value.filter(ownedLeave))
const deletions = computed(() => pending.value.filter((c) => c.decision === 'delete'))

// Kept only on this page and sent once with the start; the server holds it for the job alone
const password = ref('')
const deleteWord = ref('')
const deletionsConfirmed = computed(
  () => deleteWord.value.trim().toLowerCase() === t('review.deleteWord').toLowerCase(),
)
/** What waits in the queue if applied now: transfers without the password, deletions without the word. */
const heldTransfers = computed(() => (password.value ? 0 : transfers.value.length))
const heldDeletions = computed(() => (deletionsConfirmed.value ? 0 : deletions.value.length))
const runnable = computed(() => pending.value.length - heldTransfers.value - heldDeletions.value)

/** The chats about to be deleted, as a CSV to keep: titles, links, descriptions. */
function saveDeletions() {
  // A leading = + - @ would make a spreadsheet read the cell as a formula: a quote in front keeps it text
  const cell = (v: string | number | null) => {
    const text = String(v ?? '')
    const safe = /^[=+\-@\t\r]/.test(text) ? `'${text}` : text
    return `"${safe.replaceAll('"', '""')}"`
  }
  const rows = [
    ['title', 'link', 'members', 'about'],
    ...deletions.value.map((c) => [c.title, c.link, c.members_count, c.about]),
  ]
  const blob = new Blob([rows.map((r) => r.map(cell).join(',')).join('\n')], {
    type: 'text/csv;charset=utf-8',
  })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = 'deleted-chats.csv'
  a.click()
  // Freed a little later: some browsers start the download only after the click returns
  setTimeout(() => URL.revokeObjectURL(a.href), 1000)
}
const minutes = computed(() => Math.round((pending.value.length * 2.6) / 60))
/** Private channels being left: without an invite link there is no way back. */
const noWayBack = computed(
  // an owned chat left without an owner has its own block and warning: not counted twice
  () =>
    pending.value.filter((c) => c.decision === 'unsubscribe' && !c.username && !ownedLeave(c))
      .length,
)
/** Chats the user runs that they are about to leave: admin rights go with them. */
const leavingRun = computed(
  () => pending.value.filter((c) => c.decision === 'unsubscribe' && c.role === 'admin').length,
)
const leavingOwned = computed(
  () => pending.value.filter((c) => c.decision === 'unsubscribe' && c.role === 'owner').length,
)
const modKey = /Mac|iPhone|iPad/.test(navigator.platform) ? '⌘' : 'Ctrl'

async function load() {
  loading.value = true
  loadError.value = null
  try {
    const [p, f] = await Promise.all([
      api.get<{ items: Channel[] }>('/api/decisions?status=pending'),
      api.get<{ items: Channel[] }>('/api/decisions?status=failed'),
    ])
    pending.value = p.items
    failed.value = f.items
  } catch (err) {
    loadError.value = errorText(err)
  } finally {
    loading.value = false
  }
}

async function putBack(channel: Channel) {
  try {
    await api.del(`/api/decisions/${channel.id}`)
    pending.value = pending.value.filter((c) => c.id !== channel.id)
    failed.value = failed.value.filter((c) => c.id !== channel.id)
    deck.forget(channel.id)
  } catch (err) {
    ui.toast(errorText(err))
  }
}

async function retryFailed() {
  try {
    await api.post('/api/decisions/retry-failed')
  } catch (err) {
    return ui.toast(errorText(err))
  }
  await load()
}

async function start() {
  starting.value = true
  try {
    await apply.start({ password: password.value, confirmDeletions: deletionsConfirmed.value })
    password.value = ''
    await router.push('/apply')
  } catch (err) {
    ui.toast(errorText(err))
  } finally {
    starting.value = false
  }
}

onMounted(load)

function startIfReady() {
  if (runnable.value && !starting.value) void start()
}

// From the password and the delete word's fields too (the hotkeys stay out of fields): that is where Ctrl+Enter is
// most natural, right after typing
const onFieldKey = (e: KeyboardEvent) =>
  (e.ctrlKey || e.metaKey) && (e.preventDefault(), startIfReady())

useHotkeys({
  Escape: () => void router.push('/'),
  'mod+Enter': startIfReady,
})
</script>

<template>
  <section
    class="mx-auto flex w-full max-w-2xl flex-1 flex-col px-4 pt-8 pb-32 max-md:pt-5 max-md:pb-0"
  >
    <RouterLink
      to="/"
      class="mb-4 inline-flex w-fit items-center gap-1.5 text-sm text-muted hover:text-text"
    >
      <AppIcon name="arrowLeft" :size="16" />{{ t('review.backToDeck') }}
      <kbd class="font-mono text-[11px] text-faint max-md:hidden">Esc</kbd>
    </RouterLink>
    <h1 class="text-3xl font-bold tracking-tight">{{ t('review.title') }}</h1>
    <p class="mt-1 text-muted">{{ t('review.subtitle') }}</p>

    <div v-if="loading" class="mt-8 space-y-3">
      <div v-for="i in 4" :key="i" class="skeleton h-16 w-full rounded-xl" />
    </div>
    <div v-else-if="loadError" class="mt-10 flex flex-col items-center gap-3 text-center">
      <p class="text-danger">{{ t('common.loadFailed', { msg: loadError }) }}</p>
      <button class="key" @click="load">{{ t('common.retry') }}</button>
    </div>

    <template v-else>
      <p v-if="!pending.length && !failed.length" class="mt-10 text-center text-muted">
        {{ t('review.empty') }}
      </p>

      <!-- hand over and leave: one password for all of them -->
      <div
        v-if="transfers.length"
        class="mt-8 overflow-hidden rounded-xl border border-border-2 bg-surface"
      >
        <h2 class="block-head">
          {{ t('review.transfer') }}
          <span class="font-normal text-muted"
            >· {{ transfers.length }} · {{ t('review.transferHint') }}</span
          >
        </h2>
        <ul>
          <li v-for="c in transfers" :key="c.id" class="block-row">
            <ChannelAvatar
              :id="c.id"
              :color-index="c.color_index"
              :title="c.title"
              :src="c.avatar_url"
              :size="28"
            />
            <span class="min-w-0 truncate font-medium">{{ c.title }}</span>
            <span class="shrink-0 text-muted">→</span>
            <ChannelAvatar
              :id="c.successor_id ?? 0"
              :title="c.successor_name ?? '?'"
              :src="null"
              :size="24"
            />
            <span class="min-w-0 flex-1 truncate">{{ c.successor_name }}</span>
            <button class="put-back" :aria-label="t('review.putBack')" @click="putBack(c)">
              <AppIcon name="x" :size="14" />
            </button>
          </li>
        </ul>
        <div class="border-t border-border px-4 py-3.5">
          <p class="text-[13px] text-muted">{{ t('review.passwordHint', transfers.length) }}</p>
          <div class="mt-2.5 flex items-center gap-3">
            <input
              v-model="password"
              type="password"
              autocomplete="off"
              :aria-label="t('review.password')"
              :placeholder="t('review.password')"
              class="w-64 rounded-[10px] border border-border-2 bg-surface-3 px-3 py-2 text-sm outline-none focus:border-accent"
              @keydown.enter="onFieldKey"
            />
            <span v-if="!password" class="text-xs text-warn">{{ t('review.transfersWait') }}</span>
          </div>
        </div>
      </div>

      <!-- leaving a chat the user owns, nobody taking it over -->
      <div
        v-if="leavingOwnedList.length"
        class="mt-6 overflow-hidden rounded-xl border border-danger/40 bg-surface"
      >
        <h2 class="block-head bg-danger-soft/50">
          {{ t('review.leaveOwned') }}
          <span class="font-normal text-muted">
            · {{ leavingOwnedList.length }} · {{ t('review.leaveOwnedHint') }}
          </span>
        </h2>
        <ul>
          <li v-for="c in leavingOwnedList" :key="c.id" class="block-row">
            <ChannelAvatar
              :id="c.id"
              :color-index="c.color_index"
              :title="c.title"
              :src="c.avatar_url"
              :size="28"
            />
            <span class="min-w-0 flex-1 truncate font-medium">{{ c.title }}</span>
            <span v-if="c.members_count !== null" class="shrink-0 text-xs text-muted tabular-nums">
              {{ c.members_count }} {{ t('deck.subscribers', c.members_count) }}
            </span>
            <button class="put-back" :aria-label="t('review.putBack')" @click="putBack(c)">
              <AppIcon name="x" :size="14" />
            </button>
          </li>
        </ul>
      </div>

      <!-- deletions: all the weight of the confirmation is here, once -->
      <div
        v-if="deletions.length"
        class="mt-6 overflow-hidden rounded-xl border border-danger/40 bg-surface"
      >
        <h2 class="block-head bg-danger-soft/50">
          {{ t('review.delete') }}
          <span class="font-normal text-muted"
            >· {{ deletions.length }} · {{ t('review.deleteHint') }}</span
          >
        </h2>
        <ul>
          <li v-for="c in deletions" :key="c.id" class="block-row">
            <ChannelAvatar
              :id="c.id"
              :color-index="c.color_index"
              :title="c.title"
              :src="c.avatar_url"
              :size="28"
            />
            <span class="min-w-0 flex-1 truncate font-medium">{{ c.title }}</span>
            <span class="shrink-0 text-xs text-muted">
              {{ t(`review.kindOne.${c.kind}`) }}
              <template v-if="c.username"> · @{{ c.username }}</template>
              <template v-if="c.members_count !== null"> · {{ c.members_count }}</template>
            </span>
            <button class="put-back" :aria-label="t('review.putBack')" @click="putBack(c)">
              <AppIcon name="x" :size="14" />
            </button>
          </li>
        </ul>
        <div class="border-t border-border px-4 py-3.5">
          <button class="text-[13px] text-accent hover:underline" @click="saveDeletions">
            <AppIcon name="download" :size="13" class="mr-1 inline" />{{ t('review.saveList') }}
          </button>
          <label class="mt-2.5 flex items-center gap-3 text-[13px]">
            <i18n-t keypath="review.typeWord" tag="span">
              <template #word>
                <b class="font-mono">{{ t('review.deleteWord') }}</b>
              </template>
            </i18n-t>
            <input
              v-model="deleteWord"
              autocomplete="off"
              spellcheck="false"
              class="w-32 rounded-[10px] border bg-surface-3 px-3 py-1.5 text-sm outline-none"
              :class="deletionsConfirmed ? 'border-danger' : 'border-border-2 focus:border-accent'"
              @keydown.enter="onFieldKey"
            />
          </label>
          <p v-if="!deletionsConfirmed" class="mt-2 text-xs text-warn">
            {{ t('review.deletionsWait') }}
          </p>
        </div>
      </div>

      <div v-for="group in grouped" :key="group.decision" class="mt-8">
        <h2 class="label mb-3 flex items-center gap-2">
          <span class="flex h-6 w-6 items-center justify-center rounded-full" :class="group.cls">
            <AppIcon :name="group.icon" :size="14" :stroke="2.5" />
          </span>
          {{ t(group.label) }}
          <span class="text-muted tabular-nums">· {{ group.items.length }}</span>
        </h2>
        <p class="mb-3 text-[13px] text-muted">{{ t(`review.hints.${group.decision}`) }}</p>
        <TransitionGroup
          tag="ul"
          class="relative overflow-hidden rounded-xl border border-border bg-surface"
          leave-active-class="transition duration-200 absolute inset-x-0"
          leave-to-class="opacity-0 translate-x-6"
          move-class="transition duration-200"
        >
          <li
            v-for="c in group.items"
            :key="c.id"
            class="flex items-center gap-3 border-b border-border bg-surface px-4 py-3 last:border-b-0"
          >
            <ChannelAvatar
              :id="c.id"
              :color-index="c.color_index"
              :title="c.title"
              :src="c.avatar_url"
              :size="40"
            />
            <div class="min-w-0 flex-1">
              <div class="truncate font-medium">{{ c.title }}</div>
              <div class="truncate text-xs text-muted">
                <span v-if="c.reverts && group.decision !== 'unsubscribe'" class="text-text"
                  >↺ {{ t(`review.reverts.${c.reverts}`) }} ·
                </span>
                <span v-if="c.role !== 'member'" class="font-medium text-text"
                  >{{ t(`deck.role.${c.role}`) }} ·
                </span>
                <span v-if="c.kind === 'supergroup'">{{ t('settings.kind.supergroup') }} · </span>
                <span v-if="c.username">@{{ c.username }} · </span>
                <span
                  v-else
                  class="inline-flex items-center gap-1"
                  :class="group.decision === 'unsubscribe' ? 'font-medium text-danger' : ''"
                  ><AppIcon name="lock" :size="11" />{{
                    group.decision === 'unsubscribe' ? t('review.noWayBack') : t('deck.private')
                  }}</span
                ><span v-if="!c.username"> · </span>
                <span v-if="c.last_post_at">{{ relativeTime(c.last_post_at, locale) }}</span>
                <span v-else>{{ t('deck.neverPosted') }}</span>
                <span v-if="c.unread_count"> · {{ c.unread_count }} {{ t('deck.unread') }}</span>
              </div>
            </div>
            <button class="key shrink-0 !px-2.5 !py-1 !text-xs" @click="putBack(c)">
              {{ t('review.putBack') }}
            </button>
          </li>
        </TransitionGroup>
      </div>

      <div v-if="failed.length" class="mt-8">
        <h2 class="mb-3 flex items-center justify-between text-sm font-medium">
          <span class="flex items-center gap-2 text-danger">
            <AppIcon name="alert" :size="16" />{{ t('review.failedTitle') }} · {{ failed.length }}
          </span>
          <button class="text-accent hover:underline" @click="retryFailed">
            {{ t('results.retryFailed') }}
          </button>
        </h2>
        <ul class="overflow-hidden rounded-xl border border-border bg-surface">
          <li
            v-for="c in failed"
            :key="c.id"
            class="flex items-center gap-3 border-b border-border px-4 py-3 last:border-b-0"
          >
            <ChannelAvatar
              :id="c.id"
              :color-index="c.color_index"
              :title="c.title"
              :src="c.avatar_url"
              :size="36"
            />
            <div class="min-w-0 flex-1">
              <div class="truncate text-sm font-medium">{{ c.title }}</div>
              <div class="truncate text-xs text-danger" :title="c.error ?? ''">
                {{ t(`review.errors.${actionErrorKind(c.error)}`) }}
              </div>
            </div>
            <button class="key shrink-0 !px-2.5 !py-1 !text-xs" @click="putBack(c)">
              {{ t('review.putBack') }}
            </button>
          </li>
        </ul>
      </div>
    </template>

    <!-- On a phone it is part of the page, at its end (mt-auto keeps a short page's one at the bottom): fixed to the
         screen with a blur, Firefox left it unpainted after the keyboard of the 2FA field went away -->
    <div
      v-if="pending.length"
      class="fixed inset-x-0 bottom-0 z-20 border-t border-border bg-bg/85 px-4 py-4 pb-[calc(16px+env(safe-area-inset-bottom))] backdrop-blur-md max-md:static max-md:-mx-4 max-md:mt-auto max-md:bg-bg max-md:backdrop-blur-none"
    >
      <!-- On a phone: the warnings over a full-width button -->
      <div
        class="mx-auto flex max-w-2xl items-center gap-4 max-md:flex-col max-md:items-stretch max-md:gap-2.5"
      >
        <div class="flex-1 text-xs leading-relaxed text-muted">
          <p v-if="noWayBack" class="mb-0.5 flex items-center gap-1.5 font-medium text-danger">
            <AppIcon name="lock" :size="12" />{{ t('review.noWayBackCount', noWayBack) }}
          </p>
          <p v-if="leavingOwned" class="mb-0.5 flex items-center gap-1.5 font-medium text-danger">
            <AppIcon name="alert" :size="12" />{{ t('review.leavingOwned', leavingOwned) }}
          </p>
          <p v-if="leavingRun" class="mb-0.5 flex items-center gap-1.5 font-medium text-danger">
            <AppIcon name="alert" :size="12" />{{ t('review.leavingRun', leavingRun) }}
          </p>
          <p class="max-md:hidden">{{ t('review.pacing', { m: t('time.minutes', minutes) }) }}</p>
        </div>
        <button
          class="flex shrink-0 items-center gap-2 rounded-[10px] bg-danger-strong px-5 py-3 font-semibold text-white shadow-card hover:brightness-110 disabled:opacity-50 max-md:justify-center max-md:py-3.5"
          :disabled="starting || !runnable"
          @click="start"
        >
          {{ t('review.apply', runnable) }}
          <span v-if="heldTransfers + heldDeletions" class="font-normal opacity-80">
            · {{ t('review.waiting', heldTransfers + heldDeletions) }}
          </span>
          <kbd class="font-mono text-[11px] font-medium opacity-75 max-md:hidden"
            >{{ modKey }} ↵</kbd
          >
        </button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.block-head {
  padding: 0.75rem 1rem;
  font-size: 14px;
  font-weight: 600;
  border-bottom: 1px solid var(--border);
}
.block-row {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.6rem 1rem;
  border-bottom: 1px solid var(--border);
  font-size: 14px;
}
.block-row:last-child {
  border-bottom: none;
}
.put-back {
  flex-shrink: 0;
  border-radius: 6px;
  padding: 0.25rem;
  color: var(--faint);
}
.put-back:hover {
  background: var(--surface-3);
  color: var(--text);
}
</style>
