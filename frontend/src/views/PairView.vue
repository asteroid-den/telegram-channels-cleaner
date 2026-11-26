<script setup lang="ts">
import { useIntervalFn } from '@vueuse/core'
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import { api, ApiError } from '@/api/client'
import type { PairingState } from '@/api/types'
import AppLogo from '@/components/AppLogo.vue'

/** The phone's side of pairing: it opened the QR link and waits for the user's yes on the computer. */
const { t } = useI18n()
const route = useRoute()
const router = useRouter()

type View =
  | { kind: 'loading' }
  | { kind: 'waiting'; code: string; computer: string }
  | { kind: 'denied' }
  | { kind: 'taken' }
const view = ref<View>({ kind: 'loading' })
const offline = ref(false)

/** Where this browser stands; null once it is turned away (its cookie counts for nothing). */
async function status(): Promise<PairingState | null> {
  try {
    return await api.get<PairingState>('/api/pairing')
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) return null
    throw err
  }
}

function show(state: PairingState | null) {
  // A full load: the app starts over with the cookie that now counts
  if (state?.status === 'paired') location.replace('/')
  else if (state?.code) view.value = { kind: 'waiting', code: state.code, computer: state.computer }
  else view.value = { kind: 'denied' }
}

async function claim(token: string) {
  try {
    show(await api.post<PairingState>('/api/pairing/claim', { token }))
  } catch (err) {
    if (err instanceof ApiError && err.type === 'pairing_taken') view.value = { kind: 'taken' }
    else if (err instanceof ApiError) view.value = { kind: 'denied' }
    else throw err
  }
}

const poll = useIntervalFn(
  async () => {
    if (view.value.kind !== 'waiting') return poll.pause()
    try {
      show(await status())
      offline.value = false
    } catch {
      offline.value = true
    }
  },
  1000,
  { immediate: false },
)

onMounted(async () => {
  const token = typeof route.params.token === 'string' ? route.params.token : ''
  // Out of the address bar: a reload must not claim the spent link again
  if (token) void router.replace({ name: 'pair' })
  try {
    // Already waiting or paired (a reload): the link is spent, don't claim it again
    const current = await status()
    if (current || !token) show(current)
    else await claim(token)
  } catch {
    offline.value = true
    view.value = { kind: 'denied' }
  }
  if (view.value.kind === 'waiting') poll.resume()
})
</script>

<template>
  <div
    class="mx-auto flex w-full max-w-[420px] flex-1 flex-col items-center px-6 pt-14 pb-10 text-center"
  >
    <AppLogo :size="52" />

    <div v-if="view.kind === 'loading'" class="spinner mt-10" />

    <template v-else-if="view.kind === 'waiting'">
      <h1 class="mt-5 font-display text-[22px] font-semibold">{{ t('pair.waitingTitle') }}</h1>
      <p class="mt-2 text-sm leading-relaxed text-muted">
        <i18n-t keypath="pair.waitingText" tag="span">
          <template #computer>
            <b class="text-text">{{ view.computer }}</b>
          </template>
        </i18n-t>
      </p>
      <div class="mt-8 mb-2.5 text-[12.5px] text-faint">{{ t('pair.code') }}</div>
      <div class="flex justify-center gap-2">
        <span
          v-for="(digit, i) in view.code"
          :key="i"
          class="flex h-14 w-11 items-center justify-center rounded-[10px] border border-border-2 bg-surface font-mono text-[26px] font-bold"
          >{{ digit }}</span
        >
      </div>
      <div class="spinner mt-10" />
      <div class="mt-3 text-[13px] text-faint">{{ t('pair.waiting') }}</div>
      <p class="mt-10 text-[12.5px] text-faint">{{ t('pair.otherCode') }}</p>
    </template>

    <template v-else-if="view.kind === 'taken'">
      <h1 class="mt-5 font-display text-[22px] font-semibold">{{ t('pair.takenTitle') }}</h1>
      <p class="mt-2 text-sm leading-relaxed text-muted">{{ t('pair.takenText') }}</p>
      <p class="mt-5 text-sm leading-relaxed text-muted">{{ t('pair.takenAgain') }}</p>
    </template>

    <template v-else>
      <h1 class="mt-5 font-display text-[22px] font-semibold">{{ t('pair.deniedTitle') }}</h1>
      <p class="mt-2 text-sm leading-relaxed text-muted">{{ t('pair.deniedText') }}</p>
      <p class="mt-5 text-sm leading-relaxed text-muted">{{ t('pair.again') }}</p>
    </template>

    <p v-if="offline" class="mt-6 text-[13px] text-warn">{{ t('pair.offline') }}</p>
  </div>
</template>

<style scoped>
.spinner {
  width: 34px;
  height: 34px;
  border-radius: 9999px;
  border: 3px solid var(--surface-3);
  border-top-color: var(--accent);
  animation: spin 0.9s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
