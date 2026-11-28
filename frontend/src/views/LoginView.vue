<script setup lang="ts">
import { useNow } from '@vueuse/core'
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError } from '@/api/client'
import AppIcon from '@/components/AppIcon.vue'
import QrCode from '@/components/QrCode.vue'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'

const { t, te, tm, rt } = useI18n()

/** `autofocus` works only on the page's first load: these fields come and go with the login step. */
const vFocus = { mounted: (el: HTMLElement) => el.focus() }
const auth = useAuthStore()
const ui = useUiStore()
const now = useNow({ interval: 1000 })

type Method = 'qr' | 'phone'
const method = ref<Method>('qr')
const phone = ref('')
const code = ref('')
const password = ref('')
const showPassword = ref(false)
const busy = ref(false)
const error = ref<string | null>(null)

const status = computed(() => auth.state.status)
// Other accounts are in the app: this login adds one, and giving it up goes back
const backTo = computed(
  () => auth.accounts.find((a) => a.id === auth.previous?.id) ?? auth.accounts[0] ?? null,
)

async function goBack() {
  if (!backTo.value) return
  busy.value = true
  try {
    await auth.switchTo(backTo.value)
  } catch (err) {
    error.value = describe(err)
  } finally {
    busy.value = false
  }
}
const step = computed<'method' | 'code' | 'password'>(() =>
  status.value === 'password' ? 'password' : status.value === 'code' ? 'code' : 'method',
)
const qrSteps = computed(() => (tm('login.qrSteps') as unknown[]).map((s) => rt(s as never)))
const qrSecondsLeft = computed(() => {
  if (!auth.state.qr_expires_at) return null
  return Math.max(
    0,
    Math.round((Date.parse(auth.state.qr_expires_at) - now.value.getTime()) / 1000),
  )
})
const qrFloodWait = computed(() => {
  const err = auth.state.error
  return err?.startsWith('flood_wait:') ? Number(err.split(':')[1]) : null
})

function describe(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.type === 'flood_wait') return t('login.errors.flood_wait', { s: err.retryAfter ?? '?' })
    const key = `login.errors.${err.type}`
    return te(key) ? t(key) : t('login.errors.generic', { msg: err.message })
  }
  return t('login.errors.generic', { msg: String(err) })
}

async function attempt(action: () => Promise<void>) {
  busy.value = true
  error.value = null
  try {
    await action()
  } catch (err) {
    error.value = describe(err)
  } finally {
    busy.value = false
  }
}

async function chooseMethod(next: Method) {
  method.value = next
  error.value = null
  if (next === 'qr') await attempt(() => auth.startQr())
  else if (status.value === 'qr') await attempt(() => auth.cancel())
}

const sendCode = () => attempt(() => auth.sendCode(phone.value))
const signIn = () => attempt(() => auth.signIn(code.value))
const submitPassword = () =>
  attempt(async () => {
    await auth.checkPassword(password.value)
    password.value = ''
  })
const startOver = () =>
  attempt(async () => {
    code.value = ''
    password.value = ''
    await auth.cancel()
    if (method.value === 'qr') await auth.startQr()
  })

onMounted(() => {
  void auth.loadAccounts().catch(() => undefined)
  if (status.value === 'unauthorized') void chooseMethod('qr')
  else if (status.value === 'code') method.value = 'phone'
})

watch(
  () => auth.state.error,
  (err, before) => {
    // The backend keeps reconnecting on its own; the message goes once it is through
    if (!err) {
      if (before?.startsWith('connect_failed:')) error.value = null
      return
    }
    if (err.startsWith('connect_failed:')) error.value = t('login.errors.connect_failed')
    else if (!err.startsWith('flood_wait:')) error.value = t('login.errors.generic', { msg: err })
  },
)
</script>

<template>
  <section
    class="relative flex flex-1 items-start justify-center px-4 pt-14 pb-16 sm:items-center sm:pt-0"
  >
    <button
      v-if="backTo"
      class="absolute top-4 left-4 flex items-center gap-1.5 text-sm text-accent hover:underline disabled:opacity-50 sm:left-6"
      :disabled="busy"
      @click="goBack"
    >
      <AppIcon name="chevron" :size="14" class="rotate-90" />
      {{ t('login.backTo', { name: backTo.first_name }) }}
    </button>
    <div
      class="w-full max-w-[880px] overflow-hidden rounded-[18px] border border-border-2 bg-surface shadow-card"
    >
      <div class="grid md:grid-cols-[1fr_1.05fr]">
        <div class="flex flex-col justify-between gap-8 border-border p-8 md:border-r">
          <div>
            <h1 class="text-2xl font-semibold tracking-tight">
              {{ t(backTo ? 'login.addTitle' : 'login.title') }}
            </h1>
            <p class="mt-2 text-sm leading-relaxed text-muted">
              {{ t(backTo ? 'login.addSubtitle' : 'login.subtitle') }}
            </p>
          </div>

          <ol v-if="step === 'method' && method === 'qr'" class="space-y-4">
            <li v-for="(s, i) in qrSteps" :key="i" class="flex items-start gap-3 text-sm">
              <span
                class="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent-soft text-xs font-semibold text-accent"
                >{{ i + 1 }}</span
              >
              <span class="pt-0.5">{{ s }}</span>
            </li>
          </ol>
          <div v-else-if="step === 'password'" class="flex items-start gap-3 text-sm text-muted">
            <AppIcon name="lock" class="mt-0.5 shrink-0 text-accent" />
            <div>
              <p class="font-medium text-text">{{ t('login.passwordTitle') }}</p>
              <p class="mt-1">{{ t('login.passwordSubtitle') }}</p>
            </div>
          </div>
          <div v-else class="text-sm text-muted">
            <AppIcon name="phone" class="mb-2 text-accent" />
            <p v-if="step === 'code'">{{ t('login.codeSentTo', { phone: auth.state.phone }) }}</p>
          </div>

          <p v-if="ui.mock" class="rounded-xl bg-warn-soft px-3 py-2 text-xs text-warn">
            {{ t('login.mockHint') }}
          </p>
        </div>

        <div class="flex flex-col gap-6 p-8">
          <div
            v-if="step === 'method'"
            class="flex overflow-hidden rounded-lg border border-border-2 text-[13px]"
            role="tablist"
          >
            <button
              v-for="m in ['qr', 'phone'] as const"
              :key="m"
              role="tab"
              :aria-selected="method === m"
              class="flex flex-1 items-center justify-center gap-2 py-2 transition-colors"
              :class="method === m ? 'bg-text text-bg' : 'text-muted hover:text-text'"
              @click="chooseMethod(m)"
            >
              <AppIcon :name="m === 'qr' ? 'qr' : 'phone'" :size="16" />
              {{ t(m === 'qr' ? 'login.qrTab' : 'login.phoneTab') }}
            </button>
          </div>

          <div v-if="step === 'method' && method === 'qr'" class="flex flex-col items-center gap-4">
            <QrCode :value="auth.state.qr_url" :size="232" />
            <p class="h-5 text-xs text-muted">
              <template v-if="qrFloodWait">{{ t('sync.floodWait', { s: qrFloodWait }) }}</template>
              <template v-else-if="!auth.state.qr_url">{{ t('login.qrRefreshing') }}</template>
              <template v-else-if="qrSecondsLeft !== null">{{
                t('login.qrExpiresIn', { s: qrSecondsLeft })
              }}</template>
            </p>
          </div>

          <form
            v-else-if="step === 'method' && method === 'phone'"
            class="flex flex-col gap-4"
            @submit.prevent="sendCode"
          >
            <label class="flex flex-col gap-2 text-sm">
              <span class="text-muted">{{ t('login.phoneLabel') }}</span>
              <input
                v-model="phone"
                v-focus
                type="tel"
                autocomplete="tel"
                :placeholder="t('login.phonePlaceholder')"
                class="rounded-[10px] border border-border-2 bg-surface-3 px-4 py-3 text-base outline-none focus:border-accent"
              />
            </label>
            <button
              type="submit"
              :disabled="busy || phone.replace(/\D/g, '').length < 6"
              class="rounded-[10px] bg-text py-3 font-semibold text-bg transition-opacity disabled:opacity-40"
            >
              {{ t('login.sendCode') }}
            </button>
          </form>

          <form v-else-if="step === 'code'" class="flex flex-col gap-4" @submit.prevent="signIn">
            <label class="flex flex-col gap-2 text-sm">
              <span class="text-muted">{{ t('login.codeLabel') }}</span>
              <input
                v-model="code"
                v-focus
                inputmode="numeric"
                autocomplete="one-time-code"
                maxlength="8"
                class="rounded-[10px] border border-border-2 bg-surface-3 px-4 py-3 text-center font-mono text-2xl tracking-[0.5em] outline-none focus:border-accent"
              />
            </label>
            <button
              type="submit"
              :disabled="busy || !code"
              class="rounded-[10px] bg-text py-3 font-semibold text-bg disabled:opacity-40"
            >
              {{ t('login.signIn') }}
            </button>
            <button type="button" class="text-sm text-muted hover:text-text" @click="startOver">
              {{ t('login.changePhone') }}
            </button>
          </form>

          <form
            v-else-if="step === 'password'"
            class="flex flex-col gap-4"
            @submit.prevent="submitPassword"
          >
            <label class="flex flex-col gap-2 text-sm">
              <span class="text-muted">{{ t('login.passwordLabel') }}</span>
              <div class="relative">
                <input
                  v-model="password"
                  v-focus
                  :type="showPassword ? 'text' : 'password'"
                  autocomplete="current-password"
                  class="w-full rounded-[10px] border border-border-2 bg-surface-3 px-4 py-3 pr-12 text-base outline-none focus:border-accent"
                />
                <button
                  type="button"
                  class="absolute top-1/2 right-3 -translate-y-1/2 text-muted hover:text-text"
                  :aria-label="t('login.showPassword')"
                  @click="showPassword = !showPassword"
                >
                  <AppIcon :name="showPassword ? 'eyeOff' : 'eye'" :size="18" />
                </button>
              </div>
              <span v-if="auth.state.password_hint" class="text-xs text-muted">
                {{ t('login.passwordHint', { hint: auth.state.password_hint }) }}
              </span>
            </label>
            <button
              type="submit"
              :disabled="busy || !password"
              class="rounded-[10px] bg-text py-3 font-semibold text-bg disabled:opacity-40"
            >
              {{ t('login.submitPassword') }}
            </button>
            <button type="button" class="text-sm text-muted hover:text-text" @click="startOver">
              {{ t('login.startOver') }}
            </button>
          </form>

          <p
            v-if="error"
            class="flex items-start gap-2 rounded-xl bg-danger-soft px-3 py-2 text-sm text-danger"
            role="alert"
          >
            <AppIcon name="alert" :size="16" class="mt-0.5 shrink-0" />
            {{ error }}
          </p>
        </div>
      </div>
    </div>
  </section>
</template>
