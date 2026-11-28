<script setup lang="ts">
import { useUiStore } from '@/stores/ui'

import AppIcon from './AppIcon.vue'

const ui = useUiStore()
</script>

<template>
  <!-- Read out as they come: an error toast is often the only word of what went wrong -->
  <div
    class="pointer-events-none fixed inset-x-0 bottom-6 z-50 flex flex-col items-center gap-2 px-4"
    role="status"
    aria-live="polite"
  >
    <TransitionGroup
      enter-from-class="opacity-0 translate-y-3"
      leave-to-class="opacity-0 translate-y-3"
      enter-active-class="transition duration-200"
      leave-active-class="transition duration-200"
    >
      <button
        v-for="toast in ui.toasts"
        :key="toast.id"
        class="pointer-events-auto flex max-w-md items-center gap-3 rounded-xl border border-border bg-surface px-4 py-3 text-left text-sm shadow-card"
        @click="ui.dismiss(toast.id)"
      >
        <AppIcon
          :name="toast.kind === 'error' ? 'alert' : 'check'"
          :class="toast.kind === 'error' ? 'text-danger' : 'text-success'"
        />
        <span>{{ toast.text }}</span>
      </button>
    </TransitionGroup>
  </div>
</template>
