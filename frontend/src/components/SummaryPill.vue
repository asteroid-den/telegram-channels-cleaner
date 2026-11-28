<script setup lang="ts">
import { onClickOutside, onKeyStroke } from '@vueuse/core'
import { computed, ref, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import type { Decision } from '@/api/types'
import { useNarrow } from '@/composables/useNarrow'
import { useConnectionStore } from '@/stores/connection'
import { useDeckStore } from '@/stores/deck'
import { relativeTime } from '@/utils/format'

import ChannelAvatar from './ChannelAvatar.vue'

const { t, locale } = useI18n()
const deck = useDeckStore()
const connection = useConnectionStore()
const router = useRouter()
const narrow = useNarrow()

/** Opens on hover for a quick look; a click pins it open until dismissed. */
const open = ref(false)
const pinned = ref(false)
const root = useTemplateRef<HTMLElement>('root')
let timer: ReturnType<typeof setTimeout> | undefined

function show() {
  clearTimeout(timer)
  timer = setTimeout(() => (open.value = true), 90)
}
function hide() {
  clearTimeout(timer)
  if (!pinned.value) timer = setTimeout(() => (open.value = false), 180)
}
function toggle() {
  clearTimeout(timer)
  pinned.value = !(pinned.value && open.value)
  open.value = pinned.value
}
function close() {
  open.value = pinned.value = false
}
onClickOutside(root, close)
onKeyStroke('Escape', () => open.value && close())

const history = computed(() => deck.history.slice(-6).reverse())
const next = computed(() => deck.items.slice(1, 5))

const TAG_CLASS: Record<Decision, string> = {
  keep: 'bg-success-soft text-success',
  unsubscribe: 'bg-danger-soft text-danger',
  skip: 'bg-surface-3 text-muted',
  mute: 'bg-warn-soft text-warn',
  archive: 'bg-accent-soft text-accent',
  transfer: 'bg-danger-soft text-danger',
  delete: 'bg-danger-soft text-danger',
  free_link: 'bg-accent-soft text-accent',
}

function review() {
  close()
  void router.push('/review')
}
</script>

<template>
  <div ref="root" class="relative" @pointerenter="show" @pointerleave="hide">
    <button
      class="flex h-[34px] items-center gap-2.5 rounded-full border border-border-2 bg-surface-2 pr-3 pl-2.5 text-[12.5px] whitespace-nowrap hover:bg-surface-3"
      :aria-expanded="open"
      aria-controls="deck-summary"
      @click="toggle"
    >
      <span
        class="h-2 w-2 rounded-full"
        :class="deck.counts.pending ? 'bg-danger' : 'bg-border-2'"
      />
      <span
        ><b class="font-mono">{{ deck.counts.pending }}</b
        ><span class="ml-1 max-md:sr-only">{{ t('deck.toApply') }}</span></span
      >
      <span class="hidden h-3.5 w-px bg-border-2 xl:block" />
      <span class="hidden xl:inline"
        ><b class="font-mono">{{ deck.counts.by_decision.keep }}</b>
        {{ t('deck.keptSession') }}</span
      >
      <svg
        width="10"
        height="10"
        viewBox="0 0 10 10"
        class="text-faint max-md:hidden"
        aria-hidden="true"
      >
        <path d="M2 3.5 5 6.5 8 3.5" fill="none" stroke="currentColor" stroke-width="1.5" />
      </svg>
    </button>

    <div v-if="open && narrow" class="fixed inset-0 z-30 bg-black/55" @click="close" />
    <Transition
      :enter-from-class="narrow ? 'translate-y-full' : 'opacity-0 -translate-y-1.5 scale-[.98]'"
      :leave-to-class="narrow ? 'translate-y-full' : 'opacity-0 -translate-y-1'"
      :enter-active-class="
        narrow ? 'transition duration-250 ease-out' : 'transition duration-150 ease-out'
      "
      :leave-active-class="narrow ? 'transition duration-200 ease-in' : 'transition duration-100'"
    >
      <div
        v-show="open"
        id="deck-summary"
        class="sheet-narrow absolute top-full right-0 z-40 mt-2 w-[360px] rounded-2xl border border-border-2 bg-surface p-4 shadow-card"
      >
        <dl class="mb-4 grid grid-cols-2 rounded-xl border border-border">
          <div class="px-3 py-2.5">
            <dt class="text-[11.5px] text-faint">{{ t('deck.toApply') }}</dt>
            <dd
              class="font-mono text-lg font-bold"
              :class="deck.counts.pending ? 'text-danger' : ''"
            >
              {{ deck.counts.pending }}
            </dd>
          </div>
          <div class="border-l border-border px-3 py-2.5">
            <dt class="text-[11.5px] text-faint">{{ t('deck.keptSession') }}</dt>
            <dd class="font-mono text-lg font-bold">{{ deck.counts.by_decision.keep }}</dd>
          </div>
          <div class="border-t border-border px-3 py-2.5">
            <dt class="text-[11.5px] text-faint">{{ t('deck.decided') }}</dt>
            <dd class="font-mono text-lg font-bold">{{ deck.decided }}</dd>
          </div>
          <div class="border-t border-l border-border px-3 py-2.5">
            <dt class="text-[11.5px] text-faint">{{ t('deck.left') }}</dt>
            <dd class="font-mono text-lg font-bold">{{ deck.counts.undecided }}</dd>
          </div>
        </dl>
        <p v-if="deck.eta !== null" class="-mt-2 mb-4 text-[12px] text-faint">
          {{ t('deck.eta', { m: t('time.minutes', deck.eta) }) }}
        </p>

        <div class="label mb-1.5 flex items-center justify-between">
          <span>{{ t('deck.historyTitle') }}</span>
          <button
            class="font-sans text-[12px] tracking-normal text-muted normal-case hover:text-text disabled:opacity-40"
            :disabled="!deck.history.length || deck.moving || connection.offline"
            @click="deck.undo()"
          >
            <kbd>⌫</kbd> {{ t('actions.undo').toLowerCase() }}
          </button>
        </div>
        <ul v-if="history.length" class="mb-4">
          <li
            v-for="(h, i) in history"
            :key="deck.history.length - i"
            class="flex items-center gap-2.5 border-b border-dashed border-border py-1.5 text-[13px]"
          >
            <ChannelAvatar
              :id="h.channel.id"
              :color-index="h.channel.color_index"
              :title="h.channel.title"
              :src="h.channel.avatar_url"
              :size="22"
              rounded="6px"
            />
            <span class="min-w-0 flex-1 truncate">{{ h.channel.title }}</span>
            <span class="tag" :class="TAG_CLASS[h.decision]">{{
              t(`deck.tags.${h.decision}`)
            }}</span>
          </li>
        </ul>
        <p v-else class="mb-4 text-[13px] text-faint">{{ t('deck.historyEmpty') }}</p>

        <template v-if="next.length">
          <div class="label mb-1.5">{{ t('deck.queueTitle') }}</div>
          <ul class="mb-4">
            <li
              v-for="c in next"
              :key="c.id"
              class="flex items-center gap-2.5 border-b border-dashed border-border py-1.5 text-[13px]"
            >
              <ChannelAvatar
                :id="c.id"
                :color-index="c.color_index"
                :title="c.title"
                :src="c.avatar_url"
                :size="22"
                rounded="6px"
              />
              <span class="min-w-0 flex-1 truncate">{{ c.title }}</span>
              <span class="shrink-0 text-[12px] text-faint">{{
                c.last_post_at ? relativeTime(c.last_post_at, locale) : t('deck.neverPosted')
              }}</span>
            </li>
          </ul>
        </template>

        <button
          class="w-full rounded-[10px] bg-text px-3 py-2.5 font-semibold text-bg transition-opacity disabled:opacity-35"
          :disabled="!deck.counts.pending"
          @click="review"
        >
          {{ t('deck.applyCta', { n: deck.counts.pending }) }} <kbd>↵</kbd>
        </button>
      </div>
    </Transition>
  </div>
</template>
