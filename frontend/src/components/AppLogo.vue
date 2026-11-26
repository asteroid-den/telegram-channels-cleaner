<script setup lang="ts">
import { useId } from 'vue'

// The logo in the current channel's colours (--ch / --ch2): the same mark as public/favicon.svg
defineProps<{ size?: number }>()
const id = useId()
</script>

<template>
  <svg :width="size ?? 26" :height="size ?? 26" viewBox="0 0 64 64" aria-hidden="true">
    <defs>
      <linearGradient :id="`${id}-fill`" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" class="stop-ch" />
        <stop offset="1" class="stop-ch2" />
      </linearGradient>
      <mask :id="`${id}-plane`" maskUnits="userSpaceOnUse" x="0" y="0" width="64" height="64">
        <rect width="64" height="64" fill="#fff" />
        <path
          transform="translate(12.551 19.618) scale(.2046)"
          d="M89.44,11.42c-12.53,5.19-66.27,27.45-81.12,33.52c-9.96,3.89-4.13,7.53-4.13,7.53s8.5,2.91,15.79,5.1 c7.29,2.19,11.17-0.24,11.17-0.24l34.24-23.07c12.14-8.26,9.23-1.46,6.32,1.46 c-6.32,6.32-16.76,16.27-25.5,24.29c-3.89,3.4-1.94,6.32-0.24,7.77c6.32,5.34,23.56,16.27,24.53,17 c5.13,3.63,15.22,8.86,16.76-2.19c0,0,6.07-38.13,6.07-38.13c1.94-12.87,3.89-24.77,4.13-28.17 C98.19,8.02,89.44,11.42,89.44,11.42z"
        />
      </mask>
    </defs>
    <g :mask="`url(#${id}-plane)`">
      <rect x="24" y="12" width="30" height="40" rx="7" class="tint fill-ch2" opacity=".28" />
      <rect
        x="10"
        y="10"
        width="30"
        height="40"
        rx="7"
        :fill="`url(#${id}-fill)`"
        transform="rotate(-16 25 30)"
      />
    </g>
    <g class="tint stroke-ch" stroke-width="3.2" stroke-linecap="round" opacity=".85">
      <path d="M44 24h10" />
      <path d="M46 32h8" />
      <path d="M48 40h6" />
    </g>
  </svg>
</template>

<style scoped>
.stop-ch {
  stop-color: rgb(var(--ch));
}
.stop-ch2 {
  stop-color: rgb(var(--ch2));
}
.stop-ch,
.stop-ch2,
.tint {
  transition:
    stop-color 0.5s,
    fill 0.5s,
    stroke 0.5s;
}
</style>
