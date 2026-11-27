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

    <button
      v-if="view.kind !== 'loading' && view.kind !== 'waiting'"
      class="mt-7 w-full rounded-xl bg-text py-3.5 text-[15px] font-semibold text-bg"
      @click="openCode"
    >
      {{ t('pair.enterCode') }}
    </button>

    <p v-if="offline" class="mt-6 text-[13px] text-warn">{{ t('pair.offline') }}</p>

    <Transition
      enter-from-class="opacity-0"
      enter-active-class="transition duration-200"
      leave-to-class="opacity-0"
      leave-active-class="transition duration-150"
    >
      <div v-if="entering" class="fixed inset-0 z-50 bg-black/55" @click="entering = false" />
    </Transition>
    <Transition
      enter-from-class="translate-y-full"
      enter-active-class="transition duration-250 ease-out"
      leave-to-class="translate-y-full"
      leave-active-class="transition duration-200 ease-in"
    >
      <form
        v-if="entering"
        role="dialog"
        aria-modal="true"
        :aria-label="t('pair.codeTitle')"
        class="fixed inset-x-0 bottom-0 z-50 rounded-t-[20px] border-t border-border-2 bg-surface px-[22px] pt-2.5 pb-7 text-left"
        @submit.prevent="sendCode"
        @keydown.esc="entering = false"
      >
        <div class="mx-auto mb-4 h-1 w-10 rounded-full bg-border-2" />
        <h2 class="font-display text-[19px] font-semibold">{{ t('pair.codeTitle') }}</h2>
        <p class="mt-1.5 mb-4 text-[13.5px] leading-normal text-muted">{{ t('pair.codeHint') }}</p>
        <!-- its border shows focus and errors: the global focus ring would be a second frame -->
        <input
          ref="codeInput"
          v-model="entered"
          maxlength="9"
          autocomplete="one-time-code"
          autocapitalize="none"
          autocorrect="off"
          spellcheck="false"
          enterkeyhint="go"
          :aria-label="t('pair.codeTitle')"
          :aria-invalid="!!wrong"
          class="w-full rounded-xl border-[1.5px] bg-bg px-3.5 py-3 font-mono text-[22px] font-semibold tracking-[0.12em]"
          style="outline: none"
          :class="wrong ? 'border-danger' : 'border-border-2 focus:border-accent'"
          @input="wrong = null"
        />
        <p v-if="wrong" class="mt-2 text-[13px] text-danger">{{ wrong }}</p>
        <button
          type="submit"
          class="mt-4 w-full rounded-xl bg-text py-3.5 text-[15px] font-semibold text-bg transition-opacity disabled:opacity-45"
          :disabled="typedToken().length !== 8 || sending"
        >
          {{ t('pair.connect') }}
        </button>
      </form>
    </Transition>
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
