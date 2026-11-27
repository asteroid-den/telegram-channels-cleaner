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
  | { kind: 'unpaired' }
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

/** `turnedDown`: a link was tried and failed (else the phone just opened the app unpaired). */
function show(state: PairingState | null, turnedDown = true) {
  // A full load: the app starts over with the cookie that now counts
  if (state?.status === 'paired') location.replace('/')
  else if (state?.code) {
    view.value = { kind: 'waiting', code: state.code, computer: state.computer }
    poll.resume()
  } else view.value = { kind: turnedDown ? 'denied' : 'unpaired' }
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
    if (current || !token) show(current, !!current)
    else await claim(token)
  } catch {
    offline.value = true
    view.value = { kind: 'unpaired' }
  }
})

// The phone is on the app's address already: the code under the QR stands in for the camera
const entered = ref('')
const wrong = ref<string | null>(null)
const sending = ref(false)
const typedToken = () => entered.value.replace(/\s/g, '').toLowerCase()

/** The code is always eight characters: the eighth sends it, no reaching for the button under the keyboard. */
function onCodeInput() {
  wrong.value = null
  if (typedToken().length === 8) void sendCode()
}

async function sendCode() {
  if (typedToken().length !== 8 || sending.value) return
  sending.value = true
  wrong.value = null
  try {
    show(await api.post<PairingState>('/api/pairing/claim', { token: typedToken() }))
    offline.value = false
  } catch (err) {
    if (err instanceof ApiError && err.type === 'pairing_taken') view.value = { kind: 'taken' }
    else wrong.value = err instanceof ApiError ? t('pair.codeWrong') : t('pair.offline')
  } finally {
    sending.value = false
  }
}
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
      <h1 class="mt-5 font-display text-[22px] font-semibold">
        {{ view.kind === 'denied' ? t('pair.deniedTitle') : t('pair.unpairedTitle') }}
      </h1>
      <p class="mt-2 text-sm leading-relaxed text-muted">
        {{ view.kind === 'denied' ? t('pair.deniedText') : t('pair.unpairedText') }}
      </p>
    </template>

    <template v-if="view.kind !== 'loading' && view.kind !== 'waiting'">
      <!-- Right on the page, no button to open it: the eighth character sends the code (Enter sends it again), and
           nothing is fixed to the bottom, where a phone's keyboard covers it (Firefox doesn't shrink the page for it).
           Not focused on its own: the keyboard comes up only when the user goes for the field. -->
      <form class="mt-7 w-full" @submit.prevent="sendCode">
        <!-- its border shows focus and errors: the global focus ring would be a second frame -->
        <input
          v-model="entered"
          maxlength="9"
          autocomplete="one-time-code"
          autocapitalize="none"
          autocorrect="off"
          spellcheck="false"
          enterkeyhint="go"
          :placeholder="t('pair.codePlaceholder')"
          :aria-label="t('pair.codeTitle')"
          :aria-invalid="!!wrong"
          class="w-full rounded-xl border-[1.5px] bg-bg px-3.5 py-3 font-mono text-[22px] font-semibold tracking-[0.12em] placeholder:font-sans placeholder:text-[15px] placeholder:font-normal placeholder:tracking-normal placeholder:text-faint"
          style="outline: none"
          :class="wrong ? 'border-danger' : 'border-border-2 focus:border-accent'"
          @input="onCodeInput"
        />
        <p v-if="wrong" class="mt-2 text-left text-[13px] text-danger">{{ wrong }}</p>
        <p class="mt-2.5 text-[13px] leading-normal text-muted">{{ t('pair.codeWhere') }}</p>
      </form>
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
