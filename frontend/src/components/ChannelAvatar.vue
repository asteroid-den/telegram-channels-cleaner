<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { colorIndexOf, initials, userpicColors } from '@/utils/format'

const props = withDefaults(
  defineProps<{
    id: number
    title: string
    src: string | null
    size?: number
    rounded?: string
    /** Telegram's colour of the peer when known (an owner may pick one), else derived from the id as Telegram does */
    colorIndex?: number | null
  }>(),
  { size: 48, rounded: '9999px' },
)

const stops = computed(() => userpicColors(props.colorIndex ?? colorIndexOf(props.id)))

const failed = ref(false)
watch(
  () => props.src,
  () => (failed.value = false),
)
</script>

<template>
  <!-- the channel title is always printed next to the avatar, so it is decorative -->
  <div
    aria-hidden="true"
    class="relative shrink-0 overflow-hidden select-none"
    :style="{
      width: `${size}px`,
      height: `${size}px`,
      borderRadius: rounded,
      background: `linear-gradient(${stops[0]}, ${stops[1]})`,
    }"
  >
    <img
      v-if="src && !failed"
      :src="src"
      alt=""
      class="h-full w-full object-cover"
      draggable="false"
      loading="lazy"
      @error="failed = true"
    />
    <span
      v-else
      class="flex h-full w-full items-center justify-center font-semibold text-white"
      :style="{ fontSize: `${Math.round(size * 0.38)}px` }"
    >
      {{ initials(title) }}
    </span>
  </div>
</template>
