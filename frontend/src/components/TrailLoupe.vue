<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { Channel, Decision } from '@/api/types'
import { useNarrow } from '@/composables/useNarrow'
import { relativeTime } from '@/utils/format'

import AppIcon, { type IconName } from './AppIcon.vue'
import ChannelAvatar from './ChannelAvatar.vue'

/**
 * A zoomed-in piece of the progress bar: the decisions around the pointer as avatars, fanned
 * like the apply deck. Positions are fixed by the window, not by the focus, so the avatar
 * under the pointer doesn't slide away as it gets focus.
 */
const props = defineProps<{ trail: Channel[]; center: number; focus: number }>()
const emit = defineEmits<{ focus: [index: number]; pick: [index: number] }>()
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

const BADGE: Record<Exclude<Decision, 'skip'>, { icon: IconName; cls: string }> = {
  keep: { icon: 'check', cls: 'bg-success' },
  unsubscribe: { icon: 'x', cls: 'bg-danger-strong' },
  mute: { icon: 'bellOff', cls: 'bg-warn' },
  archive: { icon: 'archive', cls: 'bg-accent' },
  transfer: { icon: 'user', cls: 'bg-danger-strong' },
  delete: { icon: 'trash', cls: 'bg-danger-strong' },
  free_link: { icon: 'link', cls: 'bg-accent' },
}
const TAG: Record<Exclude<Decision, 'skip'>, string> = {
  keep: 'bg-success-soft text-success',
  unsubscribe: 'bg-danger-soft text-danger',
  mute: 'bg-warn-soft text-warn',
  archive: 'bg-accent-soft text-accent',
  transfer: 'bg-danger-soft text-danger',
  delete: 'bg-danger-soft text-danger',
  free_link: 'bg-accent-soft text-accent',
}
const kind = (c: Channel) => (c.decision && c.decision !== 'skip' ? c.decision : 'keep')

function place(i: number) {
  const k = i - props.focus
  const slot = i - (lo.value + HALF)
  return {
    outer: {
      transform: `translateX(calc(-50% + ${slot * (narrow.value ? 20 : 34) + Math.sign(k) * (narrow.value ? 10 : 14)}px))`,
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
    <div class="relative h-[92px]" @pointerdown.prevent="emit('pick', focus)">
      <div
        v-for="{ i, channel } in shown"
        :key="channel.id"
        class="absolute top-3 left-1/2 cursor-pointer transition-[transform,opacity] duration-300 ease-out"
        :class="place(i).dim ? 'opacity-55' : ''"
        :style="{ ...place(i).outer, zIndex: place(i).z }"
        @pointerenter="i !== focus && emit('focus', i)"
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
            :class="BADGE[kind(channel)].cls"
          >
            <AppIcon :name="BADGE[kind(channel)].icon" :size="11" :stroke="3" />
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
        <span class="tag shrink-0" :class="TAG[kind(focused)]">{{
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
