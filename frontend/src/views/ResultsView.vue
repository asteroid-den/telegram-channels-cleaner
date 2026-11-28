<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { api } from '@/api/client'
import type { Stats } from '@/api/types'
import AppIcon from '@/components/AppIcon.vue'
import { useDeckStore } from '@/stores/deck'
import { useUiStore } from '@/stores/ui'
import { errorText } from '@/utils/errors'
import { compactNumber } from '@/utils/format'

const { t, locale } = useI18n()
const deck = useDeckStore()
const ui = useUiStore()
const stats = ref<Stats | null>(null)
const loadError = ref<string | null>(null)

const AGE_ORDER = ['week', 'month', 'quarter', 'half_year', 'year', 'older', 'never'] as const

async function load() {
  loadError.value = null
  try {
    stats.value = await api.get<Stats>(`/api/stats?kind=${deck.kind}&role=${deck.role}`)
  } catch (err) {
    loadError.value = errorText(err)
  }
}
onMounted(async () => {
  await deck.settled()
  await load()
})

const applied = (decision: string) => stats.value?.decisions[decision]?.applied ?? 0
const failedTotal = computed(() =>
  Object.values(stats.value?.decisions ?? {}).reduce((sum, s) => sum + (s.failed ?? 0), 0),
)
const tiles = computed(() => [
  { label: 'results.unsubscribed', value: applied('unsubscribe'), cls: 'text-danger' },
  { label: 'results.muted', value: applied('mute'), cls: 'text-warn' },
  { label: 'results.archived', value: applied('archive'), cls: 'text-accent' },
  { label: 'results.kept', value: applied('keep'), cls: 'text-success' },
  { label: 'results.unreadCleared', value: stats.value?.unread_cleared ?? 0, cls: '' },
  { label: 'results.remaining', value: stats.value?.subscribed ?? 0, cls: '' },
])
const ageMax = computed(() => Math.max(1, ...Object.values(stats.value?.last_post_age ?? {})))

async function retryFailed() {
  try {
    await api.post(`/api/decisions/retry-failed?kind=${deck.kind}&role=${deck.role}`)
  } catch (err) {
    return ui.toast(errorText(err))
  }
  await load()
}
</script>

<template>
  <section class="mx-auto flex w-full max-w-3xl flex-1 flex-col px-4 pt-8 pb-16">
    <RouterLink
      to="/"
      class="mb-4 inline-flex w-fit items-center gap-1.5 text-sm text-muted hover:text-text"
    >
      <AppIcon name="arrowLeft" :size="16" />{{ t('results.backToDeck') }}
    </RouterLink>
    <h1 class="text-3xl font-semibold tracking-tight">{{ t('results.title') }}</h1>

    <div v-if="loadError" class="mt-10 flex flex-col items-center gap-3 text-center">
      <p class="text-danger">{{ t('common.loadFailed', { msg: loadError }) }}</p>
      <button class="key" @click="load">{{ t('common.retry') }}</button>
    </div>
    <div v-else-if="!stats" class="mt-8 grid grid-cols-2 gap-3 sm:grid-cols-3">
      <div v-for="i in 6" :key="i" class="skeleton h-24 rounded-xl" />
    </div>

    <template v-else>
      <div class="mt-8 grid grid-cols-2 gap-3 sm:grid-cols-3">
        <div
          v-for="tile in tiles"
          :key="tile.label"
          class="rounded-xl border border-border bg-surface p-5"
        >
          <div class="font-mono text-[28px] font-bold tabular-nums" :class="tile.cls">
            {{ compactNumber(tile.value, locale) }}
          </div>
          <div class="mt-1 text-sm text-muted">{{ t(tile.label) }}</div>
        </div>
      </div>

      <div
        v-if="failedTotal"
        class="mt-4 flex items-center justify-between rounded-xl bg-danger-soft px-5 py-3 text-sm text-danger"
      >
        <span class="flex items-center gap-2"
          ><AppIcon name="alert" :size="16" />{{ t('results.failed') }}: {{ failedTotal }}</span
        >
        <button class="font-medium hover:underline" @click="retryFailed">
          {{ t('results.retryFailed') }}
        </button>
      </div>

      <div class="mt-8 rounded-xl border border-border bg-surface p-6">
        <h2 class="label">{{ t('results.ageTitle') }}</h2>
        <ul class="mt-4 space-y-2.5">
          <li
            v-for="key in AGE_ORDER"
            :key="key"
            class="grid grid-cols-[96px_1fr_40px] items-center gap-3 text-sm"
          >
            <span class="text-muted">{{ t(`results.age.${key}`) }}</span>
            <div class="h-3 overflow-hidden rounded-[3px] bg-surface-3">
              <div
                class="h-full rounded-[3px] transition-[width] duration-700"
                :class="
                  ['older', 'never'].includes(key)
                    ? 'bg-danger'
                    : key === 'year' || key === 'half_year'
                      ? 'bg-warn'
                      : 'bg-success'
                "
                :style="{ width: `${((stats.last_post_age[key] ?? 0) / ageMax) * 100}%` }"
              />
            </div>
            <span class="text-right tabular-nums">{{ stats.last_post_age[key] ?? 0 }}</span>
          </li>
        </ul>
      </div>

      <div
        class="mt-8 flex flex-col gap-3 rounded-xl border border-border bg-surface p-6 sm:flex-row sm:items-center"
      >
        <div class="flex-1">
          <h2 class="label">{{ t('results.export') }}</h2>
          <p class="mt-1 text-xs text-muted">{{ t('results.exportHint') }}</p>
        </div>
        <div class="flex gap-2">
          <a
            v-for="fmt in ['csv', 'json']"
            :key="fmt"
            :href="`/api/export?format=${fmt}&kind=${deck.kind}&role=${deck.role}`"
            class="key uppercase"
            download
          >
            <AppIcon name="download" :size="16" />{{ fmt }}
          </a>
        </div>
      </div>
    </template>
  </section>
</template>
