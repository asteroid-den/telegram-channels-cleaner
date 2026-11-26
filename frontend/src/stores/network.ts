import { defineStore } from 'pinia'
import { ref } from 'vue'

import { api, subscribe } from '@/api/client'
import type { NetworkState, PairingState } from '@/api/types'

/** The app is open on the computer it runs on: only there can phones be paired (the API says computer_only). */
export const onComputer = ['localhost', '127.0.0.1', '[::1]'].includes(location.hostname)

/** In a browser from the network (a phone), the app opens only once that browser is paired. */
export async function paired(): Promise<boolean> {
  if (onComputer) return true
  try {
    return (await api.get<PairingState>('/api/pairing')).status === 'paired'
  } catch {
    return false
  }
}

/** Phone access as the computer manages it: the network toggle, the pairing QR and the paired devices. */
export const useNetworkStore = defineStore('network', () => {
  const state = ref<NetworkState | null>(null)
  let unsubscribe: (() => void) | null = null

  const set = (next: NetworkState) => (state.value = next)
  const call = async (request: Promise<NetworkState>) => set(await request)

  /** Live while the dialog is open: a phone's request to pair comes in through it. */
  function connect() {
    if (unsubscribe) return
    unsubscribe = subscribe('/api/network/events', {
      snapshot: (data: NetworkState) => set(data),
      state: (data: NetworkState) => set(data),
    })
  }

  function disconnect() {
    unsubscribe?.()
    unsubscribe = null
  }

  return {
    state,
    connect,
    disconnect,
    load: () => call(api.get('/api/network')),
    setEnabled: (enabled: boolean) => call(api.put('/api/network', { enabled })),
    newPairing: () => call(api.post('/api/network/pairing')),
    cancelPairing: () => call(api.del('/api/network/pairing')),
    approve: () => call(api.post('/api/network/pairing/approve')),
    reject: () => call(api.post('/api/network/pairing/reject')),
    rename: (id: number, name: string) => call(api.patch(`/api/network/devices/${id}`, { name })),
    forget: (id: number) => call(api.del(`/api/network/devices/${id}`)),
  }
})
