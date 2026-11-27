<script setup lang="ts">
import { useEventListener, useNow } from '@vueuse/core'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError } from '@/api/client'
import type { Device } from '@/api/types'
import { useNetworkStore } from '@/stores/network'
import { relativeTime } from '@/utils/format'

import AppIcon from './AppIcon.vue'
import QrCode from './QrCode.vue'

const emit = defineEmits<{ close: [] }>()
const { t, locale } = useI18n()
const network = useNetworkStore()
const now = useNow({ interval: 1000 })

const state = computed(() => network.state)
/** QR for a new phone, or the list of the ones paired. */
const mode = ref<'pair' | 'devices'>('pair')
/** The phone just let in, for the heading of the list. */
const justPaired = ref<string | null>(null)
const busy = ref(false)
/** The panel shows once the state is in: the view it opens on depends on it, and a stale one would flash first. */
const ready = ref(false)
const failure = ref<string | null>(null)

const pairing = computed(() => state.value?.pairing ?? null)
const request = computed(() => pairing.value?.request ?? null)
const secondsLeft = computed(() =>
  pairing.value
    ? Math.max(0, Math.round((Date.parse(pairing.value.expires_at) - now.value.getTime()) / 1000))
    : 0,
)
const countdown = computed(() => {
  const s = secondsLeft.value
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
})
/** The pairing link's one-time part: typed in on the phone when its camera won't open the QR. */
const token = computed(() => pairing.value?.url.split('/').pop() ?? null)
/** Opens the app on a phone paired already: shown by the device list while access is on. */
const openQr = computed(() =>
  state.value?.enabled && state.value.devices.length ? state.value.open_qr : null,
)
const host = computed(() => state.value?.url?.replace(/^http:\/\//, '') ?? '')

/** What stands in the way: the app's own setup, or the last try to listen in the network. */
const problem = computed(() => {
  const s = state.value
  if (!s) return null
  if (s.unavailable_reason) return t(`phone.unavailable.${s.unavailable_reason}`)
  if (failure.value) return failure.value
  if (!s.error) return null
  const known = ['no_network', 'address_in_use']
  return known.includes(s.error)
    ? t(`phone.errors.${s.error}`, { port: location.port || '8765' })
    : t('phone.errors.other', { reason: s.error })
})

async function act(action: () => Promise<unknown>) {
  busy.value = true
  failure.value = null
  try {
    await action()
  } catch (err) {
    // The answer of a refused toggle carries no state: the next event or load brings the error with it
    if (err instanceof ApiError && err.type === 'network_unavailable') await network.load()
    else failure.value = err instanceof Error ? err.message : String(err)
  } finally {
    busy.value = false
  }
}

onMounted(async () => {
  network.connect()
  await act(network.load)
  mode.value = state.value?.devices.length ? 'devices' : 'pair'
  ready.value = true
})

// A fresh QR whenever one is due: on opening, once turned on, after the last one ran out or was turned down
watch(
  () =>
    mode.value === 'pair' &&
    !!state.value?.enabled &&
    !busy.value &&
    (!pairing.value || secondsLeft.value === 0),
  (due) => {
    if (due) void act(network.newPairing)
  },
)

function toggle() {
  if (state.value) void act(() => network.setEnabled(!state.value!.enabled))
}

async function approve() {
  const name = request.value?.name ?? null
  await act(network.approve)
  if (!failure.value) {
    justPaired.value = name
    mode.value = 'devices'
  }
}

function pairAnother() {
  justPaired.value = null
  mode.value = 'pair'
}

const editing = ref<number | null>(null)
const draft = ref('')
const nameInput = useTemplateRef<HTMLInputElement[]>('nameInput')

async function startRename(device: Device) {
  editing.value = device.id
  draft.value = device.name
  await nextTick()
  nameInput.value?.[0]?.select()
}

function saveRename() {
  const id = editing.value
  editing.value = null
  const name = draft.value.trim()
  const device = state.value?.devices.find((d) => d.id === id)
  if (id !== null && name && name !== device?.name) void act(() => network.rename(id, name))
}

function close() {
  // A QR nobody used stops working with the dialog
  if (pairing.value) void network.cancelPairing().catch(() => undefined)
  emit('close')
}

onBeforeUnmount(() => network.disconnect())
useEventListener(window, 'keydown', onKey)

function onKey(e: KeyboardEvent) {
  if (e.key !== 'Escape' || editing.value !== null) return
  e.preventDefault()
  if (!request.value) close()
}
</script>

<template>
  <!-- data-hotkeys-off: while open, the deck's own keys stay quiet -->
  <div
    data-hotkeys-off
    class="fixed inset-0 z-50 flex items-center justify-center bg-bg/70 p-4 backdrop-blur-[2px]"
    @pointerdown.self="request ? undefined : close()"
  >
    <!-- The panel comes in once the state is known, and fades from one view to the other -->
    <Transition
      mode="out-in"
      enter-from-class="opacity-0 translate-y-2 scale-[.97]"
      enter-active-class="transition duration-200 ease-out"
      leave-to-class="opacity-0 scale-[.98]"
      leave-active-class="transition duration-100 ease-in"
    >
      <!-- Pairing: what it is, the toggle, the steps; the QR on the right -->
      <div
        v-if="ready && mode === 'pair'"
        role="dialog"
        aria-modal="true"
        :aria-label="t('phone.title')"
        class="grid w-full max-w-[820px] overflow-hidden rounded-2xl border border-border-2 bg-surface shadow-card transition md:grid-cols-[1fr_300px]"
        :class="request ? 'pointer-events-none opacity-35 blur-[1px]' : ''"
      >
        <div class="p-7">
          <div class="flex items-start justify-between gap-4">
            <h2 class="font-display text-xl font-semibold">{{ t('phone.title') }}</h2>
            <button
              class="-mt-1 -mr-2 rounded-lg p-1.5 text-faint hover:bg-surface-2 hover:text-text"
              :aria-label="t('common.close')"
              @click="close"
            >
              <AppIcon name="x" :size="18" />
            </button>
          </div>
          <p class="mt-2 mb-4 text-[13.5px] leading-relaxed text-muted">{{ t('phone.intro') }}</p>

          <div class="flex items-center gap-3 rounded-xl border border-border-2 px-3.5 py-3">
            <span class="flex-1 text-[13.5px]">
              {{ t('phone.toggle') }}
              <small class="mt-0.5 block text-xs text-faint">
                {{ state?.enabled ? t('phone.toggleOn', { host }) : t('phone.toggleOff') }}
              </small>
            </span>
            <button
              role="switch"
              :aria-checked="!!state?.enabled"
              :aria-label="t('phone.toggle')"
              :disabled="!state?.available || busy"
              class="switch"
              @click="toggle"
            />
          </div>
          <p v-if="problem" class="mt-3 text-[13px] text-danger">{{ problem }}</p>

          <ol class="mt-5 mb-5 space-y-3">
            <li
              v-for="(step, i) in [t('phone.step1'), t('phone.step2'), t('phone.step3')]"
              :key="i"
              class="flex items-start gap-3 text-[13.5px]"
            >
              <b
                class="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent-soft text-xs text-accent"
                >{{ i + 1 }}</b
              >
              {{ step }}
            </li>
          </ol>
          <div
            class="rounded-[10px] border border-warn/35 bg-warn-soft px-3 py-2.5 text-[12.5px] text-warn"
          >
            {{ t('phone.publicNetwork') }}
          </div>
        </div>

        <div
          class="flex flex-col items-center justify-center gap-3 border-t border-border bg-surface-2 p-6 md:border-t-0 md:border-l"
        >
          <template v-if="state?.enabled">
            <QrCode :value="pairing?.qr ?? null" :size="196" plain />
            <!-- When the camera won't open it, or the page it goes through doesn't load: the phone opens the app's
                 address and types this in on the pairing screen -->
            <span v-if="token" class="flex gap-1" :aria-label="token">
              <b
                v-for="(c, i) in token"
                :key="i"
                class="flex h-[30px] w-[22px] items-center justify-center rounded-md border border-border-2 bg-surface font-mono text-[15px] font-bold"
                >{{ c }}</b
              >
            </span>
            <span class="-mt-1 max-w-[230px] text-center text-xs leading-snug text-faint">
              <i18n-t keypath="phone.typeCode" tag="span">
                <template #host>
                  <span class="font-mono text-muted">{{ host }}</span>
                </template>
              </i18n-t>
            </span>
            <span class="text-xs text-faint">{{ t('phone.expiresIn', { time: countdown }) }}</span>
          </template>
          <p v-else class="max-w-[200px] text-center text-[13px] text-faint">
            {{ t('phone.qrOff') }}
          </p>
          <button
            v-if="state?.devices.length"
            class="mt-1 text-[12.5px] text-accent hover:underline"
            @click="mode = 'devices'"
          >
            {{ t('phone.showDevices', { n: state.devices.length }) }}
          </button>
        </div>
      </div>

      <!-- Paired devices; with access on, a QR on the right opens the app on one of them -->
      <div
        v-else-if="ready"
        role="dialog"
        aria-modal="true"
        :aria-label="t('phone.devices')"
        class="grid w-full overflow-hidden rounded-2xl border border-border-2 bg-surface shadow-card"
        :class="openQr ? 'max-w-[820px] md:grid-cols-[1fr_260px]' : 'max-w-[560px]'"
      >
        <div class="px-6 py-6">
          <h2 class="font-display text-xl font-semibold">
            <template v-if="justPaired">
              <span class="text-success">✓</span> {{ t('phone.paired', { name: justPaired }) }}
            </template>
            <template v-else>{{ t('phone.title') }}</template>
          </h2>
          <p class="mt-1.5 mb-4 text-[13.5px] text-muted">{{ t('phone.shared') }}</p>

          <div class="flex items-center gap-3 rounded-xl border border-border-2 px-3.5 py-3">
            <span class="flex-1 text-[13.5px]">
              {{ t('phone.toggle') }}
              <small class="mt-0.5 block font-mono text-xs text-faint">
                {{ state?.enabled ? state.url : t('phone.toggleOffPaired') }}
              </small>
            </span>
            <button
              role="switch"
              :aria-checked="!!state?.enabled"
              :aria-label="t('phone.toggle')"
              :disabled="!state?.available || busy"
              class="switch"
              @click="toggle"
            />
          </div>
          <p v-if="problem" class="mt-3 text-[13px] text-danger">{{ problem }}</p>

          <h3 class="mt-5 mb-1 text-[11px] font-semibold tracking-[0.07em] text-faint uppercase">
            {{ t('phone.devices') }}
          </h3>
          <p v-if="!state?.devices.length" class="py-3 text-[13px] text-faint">
            {{ t('phone.noDevices') }}
          </p>
          <div
            v-for="device in state?.devices ?? []"
            :key="device.id"
            class="flex items-center gap-3 border-t border-border py-3 text-[13.5px] first-of-type:border-t-0"
          >
            <AppIcon name="smartphone" :size="22" class="shrink-0 text-muted" />
            <span class="min-w-0 flex-1">
              <input
                v-if="editing === device.id"
                ref="nameInput"
                v-model="draft"
                maxlength="64"
                class="w-full rounded-md border border-border-2 bg-bg px-2 py-0.5 outline-none focus:border-accent"
                @keydown.enter.prevent="saveRename"
                @keydown.esc.prevent.stop="editing = null"
                @blur="saveRename"
              />
              <button
                v-else
                class="block max-w-full truncate text-left hover:underline"
                :title="t('phone.rename')"
                @click="startRename(device)"
              >
                {{ device.name }}
              </button>
              <small class="block text-xs text-faint">
                {{ relativeTime(device.last_seen_at, locale, now.getTime()) }}
                <template v-if="device.last_ip"> · {{ device.last_ip }}</template>
              </small>
            </span>
            <button
              class="shrink-0 rounded-lg border border-danger/35 px-2.5 py-1 text-[12.5px] text-danger hover:bg-danger-soft"
              @click="act(() => network.forget(device.id))"
            >
              {{ t('phone.disconnect') }}
            </button>
          </div>

          <div class="mt-4 flex justify-end gap-2">
            <button class="btn" :disabled="!state?.enabled" @click="pairAnother">
              {{ state?.devices.length ? t('phone.pairAnother') : t('phone.pairFirst') }}
            </button>
            <button class="btn primary" @click="close">{{ t('common.done') }}</button>
          </div>
        </div>
        <div
          v-if="openQr"
          class="flex flex-col items-center justify-center gap-3 border-t border-border bg-surface-2 p-6 text-center md:border-t-0 md:border-l"
        >
          <QrCode :value="openQr" :size="160" plain />
          <span class="font-mono text-[13px] font-medium select-all">{{ host }}</span>
          <span class="max-w-[200px] text-xs leading-snug text-faint">{{ t('phone.openQr') }}</span>
        </div>
      </div>
    </Transition>

    <!-- A phone opened the link: let it in only if it shows the same code (variant B) -->
    <Transition
      enter-from-class="opacity-0 scale-[.95]"
      enter-active-class="transition duration-200 ease-out"
      leave-to-class="opacity-0 scale-[.97]"
      leave-active-class="transition duration-100 ease-in"
    >
      <div
        v-if="ready && mode === 'pair' && request && pairing"
        role="alertdialog"
        aria-modal="true"
        :aria-label="t('phone.requestTitle', { name: request.name })"
        class="absolute w-full max-w-[440px] rounded-2xl border border-border-2 bg-surface px-7 py-6 text-center shadow-card"
      >
        <span
          class="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-surface-3 text-accent"
        >
          <AppIcon name="smartphone" :size="26" />
        </span>
        <h3 class="mt-3.5 mb-1.5 font-display text-lg font-semibold">
          {{ t('phone.requestTitle', { name: request.name }) }}
        </h3>
        <p class="mb-4 text-[13.5px] leading-relaxed text-muted">
          {{ t('phone.requestText', { ip: request.ip ?? '?' }) }}
        </p>
        <div class="flex justify-center gap-2">
          <span
            v-for="(digit, i) in pairing.code"
            :key="i"
            class="flex h-14 w-11 items-center justify-center rounded-[10px] border border-border-2 bg-bg font-mono text-[26px] font-bold"
            >{{ digit }}</span
          >
        </div>
        <div class="mt-5 grid grid-cols-2 gap-2.5">
          <button class="btn danger" :disabled="busy" @click="act(network.reject)">
            {{ t('phone.reject') }}
          </button>
          <button class="btn primary" :disabled="busy" @click="approve">
            {{ t('phone.approve') }}
          </button>
        </div>
        <p v-if="failure" class="mt-3 text-[13px] text-danger">{{ failure }}</p>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.switch {
  position: relative;
  width: 38px;
  height: 22px;
  flex-shrink: 0;
  border-radius: 9999px;
  background: var(--surface-3);
  transition: background 0.15s;
}
.switch::after {
  content: '';
  position: absolute;
  top: 3px;
  left: 3px;
  width: 16px;
  height: 16px;
  border-radius: 9999px;
  background: var(--muted);
  transition:
    transform 0.15s,
    background 0.15s;
}
.switch[aria-checked='true'] {
  background: var(--accent);
}
.switch[aria-checked='true']::after {
  transform: translateX(16px);
  background: #fff;
}
.switch:disabled {
  opacity: 0.5;
}
.btn {
  border-radius: 10px;
  border: 1px solid var(--border-2);
  padding: 0.55rem 0.95rem;
  font-size: 13.5px;
  font-weight: 600;
}
.btn:hover:not(:disabled) {
  background: var(--surface-2);
}
.btn:disabled {
  opacity: 0.45;
}
.btn.primary {
  border-color: transparent;
  background: var(--text);
  color: var(--bg);
}
.btn.danger {
  color: var(--danger);
  border-color: color-mix(in srgb, var(--danger) 35%, transparent);
}
</style>
