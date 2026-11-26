<script setup lang="ts">
import { computed, ref, useTemplateRef, watch } from 'vue'

import type { DeckCounts } from '@/api/types'
import { useKindI18n } from '@/composables/useKindI18n'
import { useDeckStore } from '@/stores/deck'

import TrailLoupe from './TrailLoupe.vue'

const { t, tk } = useKindI18n()
const deck = useDeckStore()

/**
 * What the bar shows. It follows the store, except while "+1" chips are flying: then it
 * waits for them to land, so the bar grows at the moment the chip hits it.
 */
const copy = (c: DeckCounts): DeckCounts => ({ ...c, by_decision: { ...c.by_decision } })
const shown = ref<DeckCounts>(copy(deck.counts))
watch(
  () => [deck.counts, deck.chipsInFlight] as const,
  () => {
    if (deck.chipsInFlight === 0) shown.value = copy(deck.counts)
  },
  { deep: true },
)

const pulse = ref(false)
watch(
  () => deck.landed,
  () => {
    shown.value = copy(deck.counts)
    pulse.value = false
    requestAnimationFrame(() => (pulse.value = true))
  },
)

const decided = computed(() => shown.value.total - shown.value.undecided)
const pct = computed(() => (shown.value.total ? (decided.value / shown.value.total) * 100 : 0))

const RUN_CLASS: Record<string, string> = {
  k: 'bg-success',
  u: 'bg-danger',
  m: 'bg-warn',
  a: 'bg-accent',
  t: 'bg-danger',
  d: 'bg-danger',
  l: 'bg-accent',
}

// The loupe: hover the bar to see the decisions around the pointer, click to rewind
const hit = useTemplateRef<HTMLElement>('hit')
const open = ref(false)
const inLoupe = ref(false)
const center = ref(0)
const focus = ref(0)
const loupeLeft = ref(0)
let hideTimer: ReturnType<typeof setTimeout> | undefined
const LOUPE_W = 560

const step = computed(() => (shown.value.total ? 100 / shown.value.total : 0))
const windowLo = computed(() => Math.max(0, Math.min(deck.trail.length - 15, center.value - 7)))
const windowHi = computed(() => Math.min(deck.trail.length, windowLo.value + 15))

function indexAt(clientX: number): number | null {
  const el = hit.value
  if (!el || !deck.trail.length || !shown.value.total) return null
  const r = el.getBoundingClientRect()
  const x = clientX - r.left
  const filled = (deck.trail.length / shown.value.total) * r.width
  if (x > filled + 8) return null // past the decided part
  return Math.max(0, Math.min(deck.trail.length - 1, Math.floor((x / r.width) * shown.value.total)))
}

function onBarMove(e: PointerEvent) {
  // Moving inside the loupe is precise picking there, not hovering the bar.
  if ((e.target as Element).closest('[data-loupe]')) return
  inLoupe.value = false
  const i = indexAt(e.clientX)
  if (i === null) return
  clearTimeout(hideTimer)
  center.value = focus.value = i
  const r = hit.value!.getBoundingClientRect()
  const want = e.clientX - LOUPE_W / 2
  loupeLeft.value = Math.max(12, Math.min(window.innerWidth - LOUPE_W - 12, want)) - r.left
  open.value = true
}
function onLeave() {
  clearTimeout(hideTimer)
  hideTimer = setTimeout(() => (open.value = inLoupe.value = false), 220)
}
function onLoupeEnter() {
  clearTimeout(hideTimer)
  inLoupe.value = true
}
function onWheel(e: WheelEvent) {
  const d = Math.sign(e.deltaY || e.deltaX)
  const last = deck.trail.length - 1
  center.value = Math.max(0, Math.min(last, center.value + d))
  focus.value = Math.max(0, Math.min(last, focus.value + d))
}
function pick(i: number) {
  open.value = inLoupe.value = false
  deck.jumpTo(i)
}
function onBarClick(e: MouseEvent) {
  const i = indexAt(e.clientX)
  if (i !== null) pick(i)
}

/** The trail as runs of the same decision, in the order they were made. */
const runs = computed(() => {
  const out: { code: string; n: number }[] = []
  for (const code of shown.value.trail) {
    const last = out[out.length - 1]
    if (last?.code === code) last.n += 1
    else out.push({ code, n: 1 })
  }
  return out
})
</script>

<template>
  <!-- the bar sits in the middle column, so it is centred over the deck; the count hangs off its left -->
  <div class="grid w-full grid-cols-[1fr_minmax(140px,460px)_1fr] items-center gap-3.5">
    <span
      class="origin-right justify-self-end text-right font-mono text-[15px] font-bold tabular-nums"
      :class="pulse ? 'count-bump' : ''"
      @animationend="pulse = false"
    >
      {{ decided }}<span class="font-medium text-faint">/{{ shown.total }}</span>
    </span>

    <div
      ref="hit"
      class="relative flex h-7 items-center"
      :class="deck.trail.length ? 'cursor-pointer' : ''"
      @pointermove="onBarMove"
      @pointerleave="onLeave"
      @click.self="onBarClick"
    >
      <div
        class="pointer-events-none relative h-2.5 w-full rounded-full bg-surface-3"
        :title="deck.eta !== null ? t('deck.eta', { m: t('time.minutes', deck.eta) }) : undefined"
        role="progressbar"
        :aria-label="tk('deck.progressLabel')"
        :aria-valuemin="0"
        :aria-valuemax="shown.total"
        :aria-valuenow="decided"
      >
        <i
          v-for="tick in [25, 50, 75]"
          :key="tick"
          class="absolute -inset-y-[3px] w-px bg-border-2"
          :style="{ left: `${tick}%` }"
        />
        <div
          class="absolute inset-y-0 left-0 flex overflow-hidden rounded-full transition-[width] duration-500 ease-out"
          :style="{ width: `${pct}%` }"
        >
          <span
            v-for="(r, i) in runs"
            :key="i"
            class="h-full transition-[flex-grow] duration-500 ease-out"
            :class="RUN_CLASS[r.code]"
            :style="{ flex: `${r.n} 0 0` }"
          />
        </div>
        <!-- the piece of the bar shown in the loupe -->
        <span
          v-if="open"
          class="absolute -inset-y-[4px] rounded-md border-[1.5px] border-text shadow-[0_0_0_3px_var(--bg)]"
          :style="{
            left: `calc(${windowLo * step}% - 2px)`,
            width: `calc(${(windowHi - windowLo) * step}% + 4px)`,
          }"
        />
        <!-- where you are while rewinding -->
        <span
          v-if="deck.cursor !== null"
          class="absolute -inset-y-[5px] w-[3px] -translate-x-1/2 rounded-full bg-text shadow-[0_0_0_2px_var(--surface)] transition-[left] duration-300 ease-out"
          :style="{ left: `${(deck.cursor + 0.5) * step}%` }"
        />
        <!-- invisible anchor: where the "+1" chip lands -->
        <span
          data-progress-edge
          aria-hidden="true"
          class="absolute top-1/2 h-px w-px transition-[left] duration-500 ease-out"
          :style="{ left: `${pct}%` }"
        />
      </div>

      <Transition
        enter-from-class="opacity-0 -translate-y-1.5"
        leave-to-class="opacity-0 -translate-y-1"
        enter-active-class="transition duration-150 ease-out"
        leave-active-class="transition duration-100"
      >
        <div
          v-if="open && deck.trail.length"
          data-loupe
          class="absolute top-full z-40 pt-2"
          :style="{ left: `${loupeLeft}px` }"
          @pointerenter="onLoupeEnter"
          @wheel.prevent="onWheel"
        >
          <TrailLoupe
            :trail="deck.trail"
            :center="center"
            :focus="focus"
            @focus="(i) => (focus = i)"
            @pick="pick"
          />
        </div>
      </Transition>
    </div>
  </div>
</template>

<style scoped>
.count-bump {
  animation: count-bump 0.5s cubic-bezier(0.2, 0.8, 0.2, 1);
}
@keyframes count-bump {
  35% {
    transform: scale(1.2);
    color: rgb(var(--ch-ink));
  }
}
</style>
