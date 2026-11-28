<script setup lang="ts">
import { useNow } from '@vueuse/core'
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'

import type { ApplyItem, Decision } from '@/api/types'
import AppIcon, { type IconName } from '@/components/AppIcon.vue'
import ChannelAvatar from '@/components/ChannelAvatar.vue'
import { useHotkeys } from '@/composables/useHotkeys'
import { useApplyStore } from '@/stores/apply'
import { useDeckStore } from '@/stores/deck'
import { actionErrorKind } from '@/utils/errors'
import { DECISIONS, FILL } from '@/utils/decisions'

const { t } = useI18n()
const apply = useApplyStore()
const deck = useDeckStore()
const now = useNow({ interval: 250 })

const VISIBLE = 14

onMounted(() => apply.connect())

const router = useRouter()
// Once the job is over: Enter goes on to the results, Esc back to the channels.
useHotkeys({
  Enter: () => !apply.running && void router.push('/results'),
  Escape: () => !apply.running && void router.push('/'),
})
onBeforeUnmount(() => {
  apply.disconnect()
  deck.clear() // the deck must be reloaded after channels were left
})

const state = computed(() => apply.state)
const queue = computed(() =>
  state.value.items.filter((i) => i.status === 'queued' || i.status === 'running'),
)
const shown = computed(() => queue.value.slice(0, VISIBLE))
const hidden = computed(() => Math.max(0, queue.value.length - VISIBLE))
const failedItems = computed(() => state.value.items.filter((i) => i.status === 'failed'))
const held = computed(() => state.value.held_transfers + state.value.held_deletions)

/** Why an item failed, in words; a too fresh session says how long Telegram wants to wait. */
function reason(item: ApplyItem): string {
  const wait = item.retry_after
  if (item.error_code === 'too_fresh' && wait) {
    const left =
      wait >= 3600
        ? t('time.hoursShort', { n: Math.ceil(wait / 3600) })
        : t('time.minutesShort', { n: Math.ceil(wait / 60) })
    return t('apply.tooFreshIn', { t: left })
  }
  return t(`review.errors.${item.error_code ?? actionErrorKind(item.error)}`)
}
const current = computed(() => state.value.items.find((i) => i.status === 'running') ?? null)
const finished = computed(() => ['finished', 'cancelled', 'error'].includes(state.value.status))
const floodLeft = computed(() =>
  state.value.flood_wait_until
    ? Math.max(0, Math.ceil(state.value.flood_wait_until - now.value.getTime() / 1000))
    : null,
)

/** An item's badge: a "keep" (or "later") here only takes back a mute/archive applied earlier. */
function badge(decision: Decision): { icon: IconName; cls: string; verb: string } {
  if (decision === 'keep' || decision === 'skip')
    return { icon: 'undo', cls: FILL.muted, verb: 'review.revert' }
  const meta = DECISIONS[decision]
  return { icon: meta.icon, cls: FILL[meta.tone], verb: meta.label }
}

const avatarUrl = (id: number, hasPhoto: boolean) =>
  hasPhoto ? `/api/channels/${id}/avatar` : null

// Deck geometry: the first card is "in focus" (flat, a bit larger); the rest fan out to the
// right in half-profile, overlapping each other like a hand of cards.
const CARD = 104
const FOCUS_GAP = 100
const STEP = 46

function offsetOf(index: number): number {
  return index === 0 ? 0 : FOCUS_GAP + (index - 1) * STEP
}

const deckWidth = computed(() => (shown.value.length ? offsetOf(shown.value.length - 1) + CARD : 0))

function cardTransform(index: number, running: boolean): string {
  // perspective() lives in the transform itself: a perspective on an ancestor gets flattened
  // by the intermediate elements and turns the rotation into a plain squash.
  if (index === 0) return `perspective(700px) translateY(${running ? -10 : 0}px) scale(1.1)`
  return 'perspective(700px) rotateY(-42deg) scale(0.94)'
}

function statusOf(el: Element) {
  const id = Number((el as HTMLElement).dataset.id)
  return state.value.items.find((i) => i.channel_id === id)?.status
}

// Only transform and opacity here: filters (blur, grayscale) on these 3D-rotated cards made
// Firefox stop painting the rest of the deck after a failed item left.
const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)')

function onEnter(el: Element, done: () => void) {
  if (reduceMotion.matches) return done()
  el.animate(
    [
      { opacity: 0, translate: '28px 0' },
      { opacity: 1, translate: '0 0' },
    ],
    { duration: 420, easing: 'cubic-bezier(.2,.8,.3,1)' },
  ).onfinish = done
}

function onLeave(el: Element, done: () => void) {
  const failed = statusOf(el) === 'failed'
  const keyframes: Keyframe[] = reduceMotion.matches
    ? [{ opacity: 1 }, { opacity: 0 }]
    : failed
      ? [
          { opacity: 1, translate: '0 0', rotate: '0deg' },
          { opacity: 0, translate: '0 56px', rotate: '-10deg' },
        ]
      : [
          { opacity: 1, translate: '0 -10px', scale: '1' },
          { opacity: 0, translate: '0 -48px', scale: '0.82' },
        ]
  el.animate(keyframes, {
    duration: reduceMotion.matches ? 150 : failed ? 520 : 460,
    easing: 'ease-in',
    fill: 'forwards',
  }).onfinish = done
}
</script>

<template>
  <section class="flex flex-1 flex-col items-center px-4 pt-6 pb-12">
    <div class="w-full max-w-3xl">
      <div class="flex items-end justify-between gap-4">
        <div>
          <h1 class="text-3xl font-semibold tracking-tight">
            {{
              state.status === 'finished'
                ? t('apply.finished')
                : state.status === 'cancelled'
                  ? t('apply.cancelled')
                  : t('apply.title')
            }}
          </h1>
          <p class="mt-1 h-5 truncate text-sm text-muted" aria-live="polite">
            <template v-if="current">
              {{ t(badge(current.decision).verb) }} ·
              <span class="text-text">{{ current.title }}</span>
            </template>
          </p>
        </div>
        <div class="text-right font-mono text-2xl font-bold tabular-nums">
          {{ t('apply.progress', { done: state.done + state.failed, total: state.total }) }}
        </div>
      </div>

      <div class="mt-4 h-1 overflow-hidden rounded bg-border">
        <div
          class="h-full rounded transition-[width] duration-500 ease-out"
          :class="state.failed ? 'bg-gradient-to-r from-success to-warn' : 'bg-success'"
          :style="{ width: `${apply.progress * 100}%` }"
        />
      </div>

      <Transition
        enter-from-class="opacity-0 -translate-y-1"
        enter-active-class="transition"
        leave-to-class="opacity-0"
        leave-active-class="transition"
      >
        <p
          v-if="floodLeft !== null"
          class="mt-4 flex items-center gap-2 rounded-lg bg-warn-soft px-4 py-2.5 text-sm text-warn"
        >
          <AppIcon name="clock" :size="16" />{{ t('apply.floodWait', { s: floodLeft }) }}
        </p>
      </Transition>
      <p
        v-if="state.status === 'error'"
        class="mt-4 rounded-xl bg-danger-soft px-4 py-2.5 text-sm text-danger"
      >
        {{ t('apply.error') }}
      </p>
    </div>

    <div class="mt-14 flex h-48 w-full max-w-4xl items-center justify-center">
      <TransitionGroup
        tag="div"
        class="relative h-[124px] shrink-0 transition-[width] duration-500 ease-out"
        :style="{ width: `${deckWidth}px` }"
        :css="false"
        @enter="onEnter"
        @leave="onLeave"
      >
        <div
          v-for="(item, i) in shown"
          :key="item.channel_id"
          :data-id="item.channel_id"
          class="absolute top-2.5 left-0 w-[104px] transition-transform duration-500 ease-out"
          :style="{ zIndex: VISIBLE - i, transform: `translateX(${offsetOf(i)}px)` }"
        >
          <div
            class="relative transition-transform duration-500 ease-out"
            :style="{ transform: cardTransform(i, item.status === 'running') }"
          >
            <div
              class="overflow-hidden rounded-[18px] shadow-card ring-1 ring-black/10 transition-shadow"
              :class="item.status === 'running' ? 'ring-4 !ring-accent' : ''"
            >
              <ChannelAvatar
                :id="item.channel_id"
                :color-index="item.color_index"
                :title="item.title"
                :src="avatarUrl(item.channel_id, item.has_photo)"
                :size="104"
                rounded="18px"
              />
            </div>
            <span
              class="absolute -right-1.5 -bottom-1.5 flex h-7 w-7 items-center justify-center rounded-full text-white ring-[3px] ring-bg"
              :class="badge(item.decision).cls"
            >
              <AppIcon :name="badge(item.decision).icon" :size="14" :stroke="3" />
            </span>
            <span
              v-if="item.status === 'running'"
              class="absolute -top-2 -left-2 h-6 w-6 animate-spin rounded-full border-[3px] border-accent/30 border-t-accent"
            />
          </div>
        </div>
      </TransitionGroup>
      <span v-if="hidden" class="tag ml-4 shrink-0 border border-border-2 text-muted"
        >+{{ hidden }}</span
      >
      <div v-if="finished && !queue.length" class="flex flex-col items-center gap-3 text-success">
        <div class="flex h-20 w-20 items-center justify-center rounded-2xl bg-success-soft">
          <AppIcon name="check" :size="38" :stroke="2.5" />
        </div>
      </div>
    </div>

    <div v-if="failedItems.length" class="mt-6 w-full max-w-3xl">
      <p class="mb-2 text-sm text-danger">{{ t('apply.failed', { n: failedItems.length }) }}</p>
      <TransitionGroup
        tag="ul"
        class="overflow-hidden rounded-xl border border-danger/40 bg-surface"
        enter-from-class="opacity-0 translate-y-3"
        enter-active-class="transition duration-300"
      >
        <li
          v-for="item in failedItems"
          :key="item.channel_id"
          class="flex items-center gap-2.5 border-b border-border px-3 py-2 text-[13px] last:border-b-0"
          :title="item.error ?? ''"
        >
          <ChannelAvatar
            :id="item.channel_id"
            :color-index="item.color_index"
            :title="item.title"
            :src="avatarUrl(item.channel_id, item.has_photo)"
            :size="24"
          />
          <span class="max-w-56 shrink-0 truncate font-medium"
            >{{ item.title
            }}<template v-if="item.successor_name"> → {{ item.successor_name }}</template></span
          >
          <span class="min-w-0 flex-1 truncate text-right text-danger">{{ reason(item) }}</span>
        </li>
      </TransitionGroup>
    </div>

    <div
      v-if="finished && held"
      class="mt-6 w-full max-w-3xl rounded-xl bg-warn-soft px-4 py-3 text-sm text-warn"
    >
      <p v-if="state.held_transfers">{{ t('apply.heldTransfers', { n: state.held_transfers }) }}</p>
      <p v-if="state.held_deletions">{{ t('apply.heldDeletions', { n: state.held_deletions }) }}</p>
      <RouterLink to="/review" class="mt-1 inline-block font-medium underline">
        {{ t('apply.backToReview') }}
      </RouterLink>
    </div>

    <div class="mt-10 flex gap-3">
      <button v-if="apply.running" class="key" :disabled="apply.cancelling" @click="apply.cancel()">
        {{ apply.cancelling ? t('apply.cancelling') : t('apply.cancel') }}
      </button>
      <template v-else>
        <RouterLink to="/" class="key">
          <AppIcon name="arrowLeft" :size="16" />{{ t('results.backToDeck') }}<kbd>Esc</kbd>
        </RouterLink>
        <RouterLink
          to="/results"
          class="flex items-center gap-2 rounded-[10px] bg-text px-4 py-2.5 text-[13px] font-semibold text-bg"
        >
          {{ t('apply.seeResults') }}<AppIcon name="arrowRight" :size="16" />
          <kbd class="font-mono text-[11px] font-medium opacity-70">↵</kbd>
        </RouterLink>
      </template>
    </div>
  </section>
</template>
