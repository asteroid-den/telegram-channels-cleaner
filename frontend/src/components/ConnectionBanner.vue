<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import { useConnectionStore } from '@/stores/connection'
import { onComputer } from '@/stores/network'

import AppIcon from './AppIcon.vue'

const { t } = useI18n()
const connection = useConnectionStore()
const where = onComputer ? 'app' : 'computer'
</script>

<template>
  <Transition
    enter-from-class="opacity-0 -translate-y-2"
    leave-to-class="opacity-0 -translate-y-2"
    enter-active-class="transition duration-200 ease-out"
    leave-active-class="transition duration-200"
  >
    <div
      v-if="connection.offline"
      role="alert"
      class="absolute inset-x-3 top-14 z-40 mx-auto flex max-w-md items-start gap-3 rounded-xl border border-warn/40 bg-surface px-4 py-3 shadow-card"
    >
      <span class="mt-0.5 h-2.5 w-2.5 shrink-0 animate-pulse rounded-full bg-warn" />
      <span class="text-[13px] leading-snug">
        <b class="block font-semibold text-warn">{{ t(`connection.${where}.title`) }}</b>
        <span class="text-muted">{{ t(`connection.${where}.text`) }}</span>
      </span>
    </div>
    <div
      v-else-if="connection.back"
      role="status"
      class="absolute top-14 left-1/2 z-40 flex -translate-x-1/2 items-center gap-2 rounded-full border border-success/40 bg-surface px-4 py-2 text-[13px] font-semibold text-success shadow-card"
    >
      <AppIcon name="check" :size="15" :stroke="2.5" />{{ t('connection.back') }}
    </div>
  </Transition>
</template>
