<script setup lang="ts">
import { computed, onMounted, ref, useTemplateRef, watch } from 'vue'

import type { Channel } from '@/api/types'
import { useKindI18n } from '@/composables/useKindI18n'
import { useDeckStore } from '@/stores/deck'

import ChannelAvatar from './ChannelAvatar.vue'

const emit = defineEmits<{ close: [] }>()
const { t } = useKindI18n()
const deck = useDeckStore()

const LIMIT = 8

const query = ref('')
const selected = ref(0)
const input = useTemplateRef<HTMLInputElement>('input')
onMounted(() => input.value?.focus())

/** Every card of the deck: the ones still to decide, then the ones decided. */
const all = computed<Channel[]>(() => [
  ...deck.items,
  ...deck.trail.slice(0, deck.cursor ?? undefined),
])
const matches = computed(() => {
  const q = query.value.trim().toLowerCase().replace(/^@/, '')
  if (!q) return []
  return all.value
    .filter((c) => c.title.toLowerCase().includes(q) || c.username?.toLowerCase().includes(q))
    .slice(0, LIMIT)
})
watch(matches, () => (selected.value = 0))

/** Where the card is now: on top, further on in the deck, or already decided. */
function place(c: Channel): string {
  const ahead = deck.items.findIndex((i) => i.id === c.id)
  if (ahead === 0) return t('search.now')
  if (c.decision && c.decision !== 'skip')
    return t('search.decided', { d: t(`deck.tags.${c.decision}`).toLowerCase() })
  return t('search.ahead', { n: ahead + 1 })
}

function go(c: Channel | undefined) {
  if (!c) return
  deck.bringToTop(c.id)
  emit('close')
}

function onKey(e: KeyboardEvent) {
  const n = matches.value.length
  if (e.key === 'ArrowDown' && n) selected.value = (selected.value + 1) % n
  else if (e.key === 'ArrowUp' && n) selected.value = (selected.value - 1 + n) % n
  else if (e.key === 'Enter') go(matches.value[selected.value])
  else if (e.key === 'Escape') emit('close')
  else return
  e.preventDefault()
}
</script>

<template>
  <!-- data-hotkeys-off: typing here must not decide cards -->
  <div
    data-hotkeys-off
    class="fixed inset-0 z-40 flex justify-center bg-bg/50 px-4 pt-[18vh]"
    @pointerdown.self="emit('close')"
  >
    <div
      role="dialog"
      aria-modal="true"
      :aria-label="t('search.label')"
      class="h-fit w-full max-w-[560px] overflow-hidden rounded-2xl border border-border-2 bg-surface shadow-card"
    >
      <input
        ref="input"
        v-model="query"
        role="combobox"
        aria-autocomplete="list"
        aria-controls="deck-search-results"
        :aria-expanded="matches.length > 0"
        :aria-activedescendant="matches.length ? `deck-search-${selected}` : undefined"
        :placeholder="t('search.placeholder', { n: all.length })"
        autocomplete="off"
        spellcheck="false"
        class="w-full bg-transparent px-5 py-4 text-base outline-none"
        @keydown="onKey"
      />
      <ul
        v-if="matches.length"
        id="deck-search-results"
        role="listbox"
        class="border-t border-border"
      >
        <li
          v-for="(c, i) in matches"
          :id="`deck-search-${i}`"
          :key="c.id"
          role="option"
          :aria-selected="i === selected"
          class="flex cursor-pointer items-center gap-3 border-b border-border px-5 py-2.5 last:border-b-0"
          :class="i === selected ? 'bg-surface-2' : 'hover:bg-surface-2'"
          @pointerenter="selected = i"
          @click="go(c)"
        >
          <ChannelAvatar :id="c.id" :title="c.title" :src="c.avatar_url" :size="32" />
          <span class="min-w-0 flex-1">
            <span class="block truncate text-sm font-medium">{{ c.title }}</span>
            <span class="block truncate text-xs text-muted">
              {{ t(`review.kindOne.${c.kind}`) }}
              <template v-if="c.username"> · @{{ c.username }}</template>
            </span>
          </span>
          <span class="shrink-0 text-xs text-faint">{{ place(c) }}</span>
        </li>
      </ul>
      <p v-else-if="query.trim()" class="border-t border-border px-5 py-3 text-sm text-muted">
        {{ t('search.nothing') }}
      </p>
    </div>
  </div>
</template>

<style scoped>
/* the field is the whole dialog: its frame shows focus well enough */
input:focus-visible {
  outline: none;
}
</style>
