<script setup lang="ts">
import { useIntervalFn } from '@vueuse/core'
import { nextTick, onMounted, ref, useTemplateRef } from 'vue'
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
const entering = ref(false)
const entered = ref('')
const wrong = ref<string | null>(null)
const sending = ref(false)
const codeInput = useTemplateRef<HTMLInputElement>('codeInput')
const typedToken = () => entered.value.replace(/\s/g, '').toLowerCase()

async function openCode() {
  entering.value = true
  entered.value = ''
  wrong.value = null
  await nextTick()
  codeInput.value?.focus()
}

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
    entering.value = false
    offline.value = false
  } catch (err) {
    if (err instanceof ApiError && err.type === 'pairing_taken') {
      entering.value = false
      view.value = { kind: 'taken' }
    } else wrong.value = err instanceof ApiError ? t('pair.codeWrong') : t('pair.offline')
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
      <p class="mt-5 text-sm leading-relaxed text-muted">{{ t('pair.unpairedHow') }}</p>
    </template>

    <template v-if="view.kind !== 'loading' && view.kind !== 'waiting'">
      <!-- In the page itself, not a sheet at the bottom: a phone's keyboard comes up over the bottom of the screen
           (Firefox doesn't shrink the page for it), and a fixed sheet ended up behind it, half painted -->
      <form
        v-if="entering"
        class="mt-7 w-full text-left"
        @submit.prevent="sendCode"
        @keydown.esc="entering = false"
      >
        <label for="pair-code" class="text-[15px] font-semibold">{{ t('pair.codeTitle') }}</label>
        <p class="mt-1 mb-2.5 text-[13px] leading-snug text-muted">{{ t('pair.codeHint') }}</p>
        <!-- its border shows focus and errors: the global focus ring would be a second frame -->
        <input
          id="pair-code"
          ref="codeInput"
          v-model="entered"
          maxlength="9"
          autocomplete="one-time-code"
          autocapitalize="none"
          autocorrect="off"
          spellcheck="false"
          enterkeyhint="go"
          :aria-invalid="!!wrong"
          class="w-full rounded-xl border-[1.5px] bg-bg px-3.5 py-3 font-mono text-[22px] font-semibold tracking-[0.12em]"
          style="outline: none"
          :class="wrong ? 'border-danger' : 'border-border-2 focus:border-accent'"
          @input="onCodeInput"
        />
        <p v-if="wrong" class="mt-2 text-[13px] text-danger">{{ wrong }}</p>
        <!-- No Connect button: the eighth character sends the code, Enter on the keyboard sends it again -->
        <button
          type="button"
          class="mt-3 w-full rounded-xl border border-border-2 py-3.5 text-[15px] font-semibold"
          @click="entering = false"
        >
          {{ t('common.cancel') }}
        </button>
      </form>
      <button
        v-else
        class="mt-7 w-full rounded-xl bg-text py-3.5 text-[15px] font-semibold text-bg"
        @click="openCode"
      >
        {{ t('pair.enterCode') }}
      </button>
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
