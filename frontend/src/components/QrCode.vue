<script setup lang="ts">
import QRCode from 'qrcode'
import { ref, watchEffect } from 'vue'

/** `plain`: without Telegram's mark in the middle (the app's own links) */
const props = defineProps<{ value: string | null; size?: number; plain?: boolean }>()
const svg = ref('')

watchEffect(async () => {
  if (!props.value) {
    svg.value = ''
    return
  }
  svg.value = await QRCode.toString(props.value, {
    type: 'svg',
    errorCorrectionLevel: 'H', // leaves room for the logo in the middle
    margin: 0,
    color: { dark: '#111318', light: '#ffffff' },
  })
})
</script>

<template>
  <div
    class="relative rounded-2xl bg-white p-4 shadow-card"
    :style="{ width: `${(size ?? 240) + 32}px`, height: `${(size ?? 240) + 32}px` }"
  >
    <!-- SVG is generated locally by the qrcode lib from the login token -->
    <!-- eslint-disable vue/no-v-html -->
    <div
      v-if="svg"
      :key="value ?? ''"
      class="qr-fade h-full w-full [&>svg]:h-full [&>svg]:w-full"
      v-html="svg"
    />
    <!-- eslint-enable vue/no-v-html -->
    <div v-else class="skeleton h-full w-full" />
    <div
      v-if="svg && !plain"
      class="absolute top-1/2 left-1/2 flex h-12 w-12 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full bg-[#2aabee] ring-4 ring-white"
    >
      <svg width="24" height="24" viewBox="0 0 24 24" aria-hidden="true">
        <path
          fill="#fff"
          d="M5.4 11.6 17.3 7c.6-.2 1 .1.9.9l-2 9.5c-.2.7-.6.8-1.2.5l-3.3-2.4-1.6 1.5c-.2.2-.3.3-.7.3l.2-3.4 6.1-5.5c.3-.2-.1-.4-.4-.2l-7.6 4.8-3.3-1c-.7-.2-.7-.7.1-1z"
        />
      </svg>
    </div>
  </div>
</template>

<style scoped>
.qr-fade {
  animation: qr-in 0.35s ease-out;
}
@keyframes qr-in {
  from {
    opacity: 0;
    transform: scale(0.96);
  }
}
</style>
