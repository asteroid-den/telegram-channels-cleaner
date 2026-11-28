<script setup lang="ts">
import { computed } from 'vue'

/**
 * Weekly activity bars. Unknown weeks (not covered by the history we fetched) are drawn as
 * faint dashes, so a busy channel never looks like it was dead before.
 */
const props = withDefaults(
  defineProps<{ weeks: (number | null)[]; height?: number; gap?: number; mini?: boolean }>(),
  { height: 56, gap: 3, mini: false },
)

const W = 400
const max = computed(() => Math.max(1, ...props.weeks.map((w) => w ?? 0)))
const bars = computed(() => {
  const n = props.weeks.length || 1
  const gap = props.mini ? 1 : props.gap
  const bw = (W - gap * (n - 1)) / n
  return props.weeks.map((v, i) => {
    const x = i * (bw + gap)
    if (v === null) return { x, y: props.height - 2, w: bw, h: 2, unknown: true, opacity: 0.35 }
    const h = v === 0 ? 2 : Math.max(3, (v / max.value) * props.height)
    const opacity = v === 0 ? 0.25 : 0.4 + 0.6 * (i / n)
    return { x, y: props.height - h, w: bw, h, unknown: false, opacity }
  })
})
</script>

<template>
  <svg
    :viewBox="`0 0 ${W} ${height}`"
    width="100%"
    :height="height"
    preserveAspectRatio="none"
    aria-hidden="true"
  >
    <rect
      v-for="(b, i) in bars"
      :key="i"
      :x="b.x"
      :y="b.y"
      :width="b.w"
      :height="b.h"
      :rx="mini ? 0.5 : 1.5"
      :fill="b.unknown ? 'var(--faint)' : 'currentColor'"
      :opacity="b.opacity"
    />
  </svg>
</template>
