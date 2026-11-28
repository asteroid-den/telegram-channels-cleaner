<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type { Channel, Decision } from '@/api/types'
import { useNarrow } from '@/composables/useNarrow'
import type { HistoryEntry } from '@/stores/deck'

import { DECISIONS, outline } from '@/utils/decisions'

import AppIcon from './AppIcon.vue'
import ChannelCard from './ChannelCard.vue'

const props = withDefaults(
  defineProps<{ items: Channel[]; returning: HistoryEntry | null; pickOnLeft?: boolean }>(),
  { pickOnLeft: false },
)
const emit = defineEmits<{
  /** The card that flew away, by id: by the time it is gone, the list may have moved under it. */
  decide: [decision: Decision, channelId: number]
  /** A card starts flying away (button, key, zone or drag); `from` is where it was. */
  flinging: [decision: Decision, from: DOMRect]
  /** Left on a chat the user owns: what leaving means there is chosen first (hand over, leave, delete). */
  pick: []
}>()
const { t } = useI18n()

const SWIPE_X = 110
const SWIPE_Y = 130
const FLY_MS = 340

const visible = computed(() => props.items.slice(0, 3))
const dx = ref(0)
const dy = ref(0)
const dragging = ref(false)
const flying = ref<Decision | null>(null)
const entering = ref(false)
let start = { x: 0, y: 0, t: 0 }
let pointerId: number | null = null

// A key pressed mid-drag would send the card away under the finger, and the next card would carry on the gesture
const busy = computed(() => flying.value !== null || entering.value || dragging.value)

// All cards in the stack share the stage height, so the fan behind never resizes from one
// channel to the next. The front card is remembered for the "+1" chip's starting point.
let front: Element | null = null
const setFront = (el: Element) => (front = el)

function flyTarget(decision: Decision): string {
  const w = window.innerWidth
  const h = window.innerHeight
  switch (decision) {
    case 'keep':
      return `translate(${w}px, ${dy.value - 40}px) rotate(28deg)`
    case 'unsubscribe':
    case 'transfer':
    case 'delete':
      return `translate(${-w}px, ${dy.value - 40}px) rotate(-28deg)`
    case 'skip':
      return `translate(0, ${h}px) rotate(4deg)`
    default:
      return `translate(0, ${-h}px) scale(0.9)`
  }
}

/** Hovering a side zone leans the top card toward it, as a preview of the decision. */
const preview = ref<'keep' | 'unsubscribe' | null>(null)

const topStyle = computed(() => {
  if (flying.value) {
    return {
      transform: flyTarget(flying.value),
      transition: `transform ${FLY_MS}ms cubic-bezier(.4,.1,.6,1), opacity ${FLY_MS}ms`,
      opacity: flying.value === 'mute' || flying.value === 'archive' ? 0 : 1,
    }
  }
  if (entering.value) {
    return { transform: flyTarget(props.returning?.decision ?? 'keep'), transition: 'none' }
  }
  if (preview.value && !dragging.value) {
    const dir = preview.value === 'keep' ? 1 : -1
    return {
      transform: `translate(${dir * 14}px, 0) rotate(${dir * 2}deg)`,
      transition: 'transform 0.3s cubic-bezier(.2,.8,.2,1)',
    }
  }
  return {
    transform: `translate(${dx.value}px, ${dy.value}px) rotate(${dx.value / 18}deg)`,
    transition: dragging.value ? 'none' : 'transform 0.35s cubic-bezier(.2,.9,.3,1.2)',
  }
})

// The cards behind fan out to the left and right of the top one, so the deck has volume.
const WIDE_FAN = [
  { x: 0, y: 0, r: 0, s: 1 },
  { x: -34, y: 10, r: -5, s: 1 },
  { x: 34, y: 10, r: 5, s: 1 },
]
// A phone has no room at the sides for the fan: the next card peeks out from under the top one, a little narrower,
// and the one after it waits hidden behind
const NARROW_FAN = [
  { x: 0, y: 0, r: 0, s: 1 },
  { x: 0, y: 18, r: 0, s: 0.94 },
  { x: 0, y: 18, r: 0, s: 0.94 },
]
const narrow = useNarrow()

function fanAt(level: number) {
  const fan = narrow.value ? NARROW_FAN : WIDE_FAN
  const lo = fan[Math.floor(level)]!
  const hi = fan[Math.min(fan.length - 1, Math.ceil(level))]!
  const k = level - Math.floor(level)
  const mix = (a: number, b: number) => a + (b - a) * k
  return { x: mix(lo.x, hi.x), y: mix(lo.y, hi.y), r: mix(lo.r, hi.r), s: mix(lo.s, hi.s) }
}

function depthStyle(depth: number) {
  // Cards behind move toward the front as the top card is dragged away.
  const pull = Math.min(1, Math.hypot(dx.value, dy.value) / 220) * (flying.value ? 1 : 0.6)
  const { x, y, r, s } = fanAt(Math.max(0, depth - (flying.value ? 1 : pull)))
  return {
    transform: `translate(${x}px, ${y}px) rotate(${r}deg) scale(${s})`,
    transformOrigin: '50% 85%',
    // Under a finger they follow it frame by frame: a transition restarted on every move only stutters
    transition: dragging.value ? 'none' : 'transform 0.35s cubic-bezier(.2,.8,.2,1)',
  }
}

/** Which stamp to show and how strongly (0..1). */
const stamp = computed<{ decision: Decision; strength: number } | null>(() => {
  if (flying.value) return { decision: flying.value, strength: 1 }
  if (preview.value && !dragging.value) {
    const decision =
      preview.value === 'unsubscribe' && props.pickOnLeft ? 'transfer' : preview.value
    return { decision, strength: 0.35 }
  }
  if (Math.abs(dx.value) > Math.abs(dy.value)) {
    if (dx.value > 12) return { decision: 'keep', strength: Math.min(1, dx.value / SWIPE_X) }
    if (dx.value < -12)
      return {
        decision: props.pickOnLeft ? 'transfer' : 'unsubscribe',
        strength: Math.min(1, -dx.value / SWIPE_X),
      }
  } else if (dy.value > 12) {
    return { decision: 'skip', strength: Math.min(1, dy.value / SWIPE_Y) }
  }
  return null
})

/** Where a stamp sits on the card: on the side it flies away from, or in the middle. */
const STAMP_POS: Record<Decision, string> = {
  keep: 'left-5 top-[86px] -rotate-6',
  unsubscribe: 'right-5 top-[86px] rotate-6',
  transfer: 'right-5 top-[86px] rotate-6',
  delete: 'right-5 top-[86px] rotate-6',
  skip: 'left-1/2 bottom-10 -translate-x-1/2',
  mute: 'left-1/2 top-1/3 -translate-x-1/2',
  archive: 'left-1/2 top-1/3 -translate-x-1/2',
  free_link: 'left-1/2 top-1/3 -translate-x-1/2',
}
/** A stamp's word: a verdict for the three swipes, the action's own name for the rest. */
const STAMP_LABEL: Partial<Record<Decision, string>> = {
  keep: 'deck.stampKeep',
  unsubscribe: 'deck.stampLeave',
  skip: 'deck.stampSkip',
}
const stampLabel = (decision: Decision) => STAMP_LABEL[decision] ?? DECISIONS[decision].label

function onPointerDown(e: PointerEvent) {
  if (e.button !== 0) return
  if ((e.target as HTMLElement).closest('a,button')) return
  // Always swallow the browser default here, even while a card is still flying away:
  // otherwise the press starts a text selection (in Firefox — of the hidden cards below),
  // and the next press becomes a native drag of that selection, which cancels our pointer.
  e.preventDefault()
  window.getSelection()?.removeAllRanges()
  if (busy.value) return
  pointerId = e.pointerId
  ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
  dragging.value = true
  start = { x: e.clientX, y: e.clientY, t: performance.now() }
}

/** The browser took the pointer away (native gesture, alt-tab…): put the card back. */
function onPointerCancel(e: PointerEvent) {
  if (!dragging.value || e.pointerId !== pointerId) return
  dragging.value = false
  pointerId = null
  dx.value = 0
  dy.value = 0
}

let moveFrame = 0
let lastMove: { x: number; y: number } | null = null

function onPointerMove(e: PointerEvent) {
  if (!dragging.value || e.pointerId !== pointerId) return
  // One update per frame: a mouse or a pen can report several moves in one
  lastMove = { x: e.clientX, y: e.clientY }
  moveFrame ||= requestAnimationFrame(applyMove)
}

function applyMove() {
  moveFrame = 0
  if (!dragging.value || !lastMove) return
  dx.value = lastMove.x - start.x
  dy.value = Math.max(-40, lastMove.y - start.y) // only "down" is meaningful vertically
}

function onPointerUp(e: PointerEvent) {
  if (!dragging.value || e.pointerId !== pointerId) return
  // The last move counts even if its frame hasn't come yet
  if (moveFrame) {
    cancelAnimationFrame(moveFrame)
    applyMove()
  }
  dragging.value = false
  pointerId = null
  const elapsed = Math.max(1, performance.now() - start.t)
  const vx = dx.value / elapsed // px/ms
  const vy = dy.value / elapsed
  if (dx.value > SWIPE_X || (vx > 0.6 && dx.value > 40)) fling('keep')
  else if (dx.value < -SWIPE_X || (vx < -0.6 && dx.value < -40)) fling('unsubscribe')
  else if (dy.value > SWIPE_Y || (vy > 0.6 && dy.value > 50)) fling('skip')
  else {
    dx.value = 0
    dy.value = 0
  }
}

/** `picked`: the choice for an owned chat is made, the card may go (otherwise a left asks for it first). */
function fling(decision: Decision, picked = false): boolean {
  if (busy.value || !visible.value.length) return false
  if (decision === 'unsubscribe' && props.pickOnLeft && !picked) {
    preview.value = null
    dx.value = 0
    dy.value = 0
    emit('pick')
    return false
  }
  const channelId = visible.value[0]!.id
  const card = front?.querySelector('article')
  if (card) emit('flinging', decision, card.getBoundingClientRect())
  preview.value = null
  flying.value = decision
  landing = () => {
    clearTimeout(timer)
    landing = null
    // Reset and shift the list in the same tick: one render, no flicker on the next card.
    flying.value = null
    dx.value = 0
    dy.value = 0
    emit('decide', decision, channelId)
  }
  const timer = setTimeout(() => landing?.(), FLY_MS)
  return true
}

/** The decision of the card in flight, sent when it has flown away. */
let landing: (() => void) | null = null

// Leaving the deck mid-flight (Enter for the review, a link, the account menu): the decision goes now, while the
// deck can still say it; once unmounted, Vue drops whatever it emits
onBeforeUnmount(() => landing?.())

// After an undo the restored card flies back in from where it left.
watch(
  () => props.returning,
  async (entry) => {
    if (!entry || visible.value[0]?.id !== entry.channel.id) return
    entering.value = true
    dx.value = 0
    dy.value = 0
    await nextTick()
    requestAnimationFrame(() =>
      requestAnimationFrame(() => {
        entering.value = false
      }),
    )
  },
)

defineExpose({ fling, busy, preview })
</script>

<template>
  <div class="relative h-full w-full select-none" @dragstart.prevent @selectstart.prevent>
    <div
      v-for="(channel, depth) in visible"
      :key="channel.id"
      :ref="(el) => depth === 0 && el && setFront(el as Element)"
      class="card-layer absolute inset-0"
      :style="{
        zIndex: 10 - depth,
        ...(depth === 0 ? {} : depthStyle(depth)),
      }"
      :aria-hidden="depth > 0"
      :inert="depth > 0"
    >
      <div
        v-if="depth === 0"
        class="card-layer h-full w-full touch-none select-none"
        :class="dragging ? 'cursor-grabbing' : 'cursor-grab'"
        :style="topStyle"
        @pointerdown="onPointerDown"
        @pointermove="onPointerMove"
        @pointerup="onPointerUp"
        @pointercancel="onPointerCancel"
        @lostpointercapture="onPointerCancel"
      >
        <ChannelCard :channel="channel" />
        <div
          v-if="stamp"
          class="pointer-events-none absolute z-10 flex items-center gap-2 rounded-lg border-2 bg-surface-2 px-3 py-1.5 font-mono text-lg font-bold tracking-wide uppercase"
          :class="[outline(stamp.decision), STAMP_POS[stamp.decision]]"
          :style="{ opacity: stamp.strength }"
        >
          <AppIcon :name="DECISIONS[stamp.decision].icon" :size="22" :stroke="3" />
          {{ t(stampLabel(stamp.decision)) }}
        </div>
      </div>
      <!-- the next card shows its content only once the top one starts leaving -->
      <ChannelCard v-else :channel="channel" :stacked="!(depth === 1 && (dragging || flying))" />
    </div>
  </div>
</template>

<style scoped>
/* Each card is a layer of its own: moving it moves a picture already drawn, instead of repainting the screen (card,
   its shadow and the glow behind it) on every frame of a drag. A blurred backdrop on the stamp did the same */
.card-layer {
  will-change: transform;
}
</style>
