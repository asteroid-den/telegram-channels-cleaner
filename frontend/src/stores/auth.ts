import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { api, subscribe } from '@/api/client'
import type { Account, AccountsResponse, AuthState } from '@/api/types'

const INITIAL: AuthState = {
  status: 'starting',
  user: null,
  qr_url: null,
  qr_expires_at: null,
  password_hint: null,
  phone: null,
  error: null,
}

export const useAuthStore = defineStore('auth', () => {
  const state = ref<AuthState>({ ...INITIAL })
  const ready = ref(false)
  /** Accounts with a session, the active one included. */
  const accounts = ref<Account[]>([])
  /** The account being switched to, for the placeholder over the deck. */
  const switchingTo = ref<string | null>(null)
  /** Who to go back to when adding an account is given up. */
  const previous = ref<Account | null>(null)
  let unsubscribe: (() => void) | null = null

  const authorized = computed(() => state.value.status === 'authorized')

  function set(next: AuthState) {
    state.value = next
    ready.value = next.status !== 'starting'
    // The menu button shows the active account's photo, which arrives after the login
    if (next.status === 'authorized') void loadAccounts().catch(() => undefined)
  }

  function connect() {
    if (unsubscribe) return
    unsubscribe = subscribe('/api/auth/events', {
      snapshot: (data: AuthState) => set(data),
      state: (data: AuthState) => set(data),
    })
  }

  async function refresh() {
    set(await api.get<AuthState>('/api/auth/state'))
  }

  async function waitReady() {
    for (;;) {
      try {
        await refresh()
        if (ready.value) return
      } catch {
        /* backend still starting */
      }
      await new Promise((resolve) => setTimeout(resolve, 400))
    }
  }

  const startQr = async () => set(await api.post<AuthState>('/api/auth/qr/start'))
  const sendCode = async (phone: string) =>
    set(await api.post<AuthState>('/api/auth/phone/send-code', { phone }))
  const signIn = async (code: string) =>
    set(await api.post<AuthState>('/api/auth/phone/sign-in', { code }))
  const checkPassword = async (password: string) =>
    set(await api.post<AuthState>('/api/auth/password', { password }))
  const cancel = async () => set(await api.post<AuthState>('/api/auth/cancel'))
  const logout = async (wipeData: boolean) =>
    set(await api.post<AuthState>('/api/auth/logout', { wipe_data: wipeData }))

  async function loadAccounts() {
    accounts.value = (await api.get<AccountsResponse>('/api/accounts')).items
  }

  async function switchTo(account: Account) {
    switchingTo.value = account.first_name
    try {
      set(await api.post<AuthState>(`/api/accounts/${account.id}/activate`))
    } finally {
      switchingTo.value = null
    }
  }

  async function addAccount() {
    previous.value = accounts.value.find((account) => account.active) ?? null
    set(await api.post<AuthState>('/api/accounts/add'))
  }

  return {
    state,
    ready,
    authorized,
    connect,
    refresh,
    waitReady,
    startQr,
    sendCode,
    signIn,
    checkPassword,
    cancel,
    logout,
    accounts,
    switchingTo,
    previous,
    loadAccounts,
    switchTo,
    addAccount,
  }
})
