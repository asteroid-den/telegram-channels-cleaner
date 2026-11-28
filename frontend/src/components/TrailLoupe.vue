<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { Channel } from '@/api/types'
import { useNarrow } from '@/composables/useNarrow'
import { relativeTime } from '@/utils/format'

import { DECISIONS, soft, strong } from '@/utils/decisions'

import AppIcon from './AppIcon.vue'
import ChannelAvatar from './ChannelAvatar.vue'

/**
 * A zoomed-in piece of the progress bar: the decisions around the pointer as avatars, fanned
 * like the apply deck. Positions are fixed by the window, not by the focus, so the avatar
 * under the pointer doesn't slide away as it gets focus.
 */
const props = defineProps<{ trail: Channel[]; center: number; focus: number }>()
const emit = defineEmits<{
  focus: [index: number]
  scrub: [index: number]
  pick: [index: number]
}>()
const { t, locale } = useI18n()
// On a phone the 15 avatars sit closer, so the loupe fits the screen
const narrow = useNarrow()

const HALF = 7
const lo = computed(() =>
  Math.max(0, Math.min(props.trail.length - 2 * HALF - 1, props.center - HALF)),
)
const shown = computed(() => {
  const hi = Math.min(props.trail.length - 1, lo.value + 2 * HALF)
  const out: { i: number; channel: Channel }[] = []
  for (let i = lo.value; i <= hi; i++) out.push({ i, channel: props.trail[i]! })
  return out
})
const focused = computed(() => props.trail[props.focus] ?? null)

const kind = (c: Channel) => (c.decision && c.decision !== 'skip' ? c.decision : 'keep')

const slotPx = () => (narrow.value ? 20 : 34)

/**
 * Picking. A mouse picks on press. A finger slides through the trail first (one avatar per slot of
 * movement) and picks only on a tap: a swipe must not land on whatever was under it when it started.
 */
let touch: { id: number; x: number; from: number; tapped: number; moved: boolean } | null = null
function onDown(e: PointerEvent) {
  e.preventDefault()
  if (e.pointerType !== 'touch') return emit('pick', props.focus)
  const el = (e.target as Element).closest<HTMLElement>('[data-i]')
  ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
  touch = {
    id: e.pointerId,
    x: e.clientX,
    from: props.focus,
    tapped: el ? Number(el.dataset.i) : -1,
    moved: false,
  }
}
function onMove(e: PointerEvent) {
  if (touch?.id !== e.pointerId) return
  const dx = e.clientX - touch.x
  if (!touch.moved && Math.abs(dx) < 8) return
  touch.moved = true
  const i = Math.max(0, Math.min(props.trail.length - 1, touch.from - Math.round(dx / slotPx())))
  if (i !== props.focus) emit('scrub', i)
}
function onUp(e: PointerEvent) {
  if (touch?.id !== e.pointerId) return
  const { moved, tapped } = touch
  touch = null
  if (!moved && tapped >= 0) emit('pick', tapped)
}

function place(i: number) {
  const k = i - props.focus
  const slot = i - (lo.value + HALF)
  return {
    outer: {
      transform: `translateX(calc(-50% + ${slot * slotPx() + Math.sign(k) * (narrow.value ? 10 : 14)}px))`,
    },
    inner: {
      transform:
        k === 0 ? 'scale(1.12)' : `perspective(500px) rotateY(${k < 0 ? 40 : -40}deg) scale(.9)`,
    },
    z: 50 - Math.abs(k),
    dim: Math.abs(k) > 6,
  }
}
</script>

<template>
  <div
    class="w-[560px] rounded-2xl border border-border-2 bg-surface p-4 pb-3 shadow-card max-md:w-[calc(100vw-24px)]"
  >
    <div
      class="relative h-[92px] touch-none"
      @pointerdown="onDown"
      @pointermove="onMove"
      @pointerup="onUp"
      @pointercancel="touch = null"
    >
      <div
        v-for="{ i, channel } in shown"
        :key="channel.id"
        :data-i="i"
        class="absolute top-3 left-1/2 cursor-pointer transition-[transform,opacity] duration-300 ease-out"
        :class="place(i).dim ? 'opacity-55' : ''"
        :style="{ ...place(i).outer, zIndex: place(i).z }"
        @pointerenter="(e) => e.pointerType !== 'touch' && i !== focus && emit('focus', i)"
      >
        <div class="relative transition-transform duration-300 ease-out" :style="place(i).inner">
          <div
            class="overflow-hidden rounded-[14px] shadow-card"
            :class="i === focus ? 'outline-[3px] outline-offset-2 outline-text outline' : ''"
          >
            <ChannelAvatar
              :id="channel.id"
              :color-index="channel.color_index"
              :title="channel.title"
              :src="channel.avatar_url"
              :size="narrow ? 44 : 58"
              rounded="14px"
            />
          </div>
          <span
            class="absolute -right-1.5 -bottom-1.5 flex h-[22px] w-[22px] items-center justify-center rounded-full text-white ring-[3px] ring-surface"
            :class="strong(kind(channel))"
          >
            <AppIcon :name="DECISIONS[kind(channel)].icon" :size="11" :stroke="3" />
          </span>
        </div>
      </div>
    </div>

    <div
      v-if="focused"
      class="flex items-baseline justify-between gap-3 border-t border-dashed border-border pt-2"
    >
      <span class="flex min-w-0 items-baseline gap-2">
        <b class="truncate font-display text-[15px] font-semibold">{{ focused.title }}</b>
        <span class="tag shrink-0" :class="soft(kind(focused))">{{
          t(`deck.tags.${kind(focused)}`)
        }}</span>
      </span>
      <small class="shrink-0 font-mono text-[12px] text-faint">
        {{ t('deck.loupePosition', { n: focus + 1, total: trail.length }) }}
        <template v-if="focused.last_post_at">
          · {{ relativeTime(focused.last_post_at, locale) }}</template
        >
      </small>
    </div>
    <div class="mt-2 flex gap-3.5 text-[12px] text-faint">
      <span v-if="narrow">{{ t('deck.loupeTap') }}</span>
      <template v-else>
        <span>{{ t('deck.loupeClick') }}</span>
        <span>{{ t('deck.loupeWheel') }}</span>
        <span>Ctrl ← / →</span>
      </template>
    </div>
  </div>
</template>
