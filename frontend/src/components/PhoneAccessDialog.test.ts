import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { i18n } from '@/i18n'

import PhoneAccessDialog from './PhoneAccessDialog.vue'

const STATE = {
  ok: true,
  available: true,
  unavailable_reason: null,
  enabled: true,
  url: 'http://192.168.1.2:8765',
  open_qr: null,
  error: null,
  pairing: null,
  devices: [],
}

class SilentEventSource {
  addEventListener() {}
  close() {}
}

let qrAsked = 0

beforeEach(() => {
  vi.useFakeTimers()
  setActivePinia(createPinia())
  qrAsked = 0
  vi.stubGlobal('EventSource', SilentEventSource)
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init: RequestInit) => {
      if (url === '/api/network/pairing' && init.method === 'POST') {
        qrAsked += 1
        const body = { ok: false, type: 'internal_error', message: 'Boom' }
        return Promise.resolve(new Response(JSON.stringify(body), { status: 500 }))
      }
      return Promise.resolve(new Response(JSON.stringify(STATE)))
    }),
  )
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('PhoneAccessDialog', () => {
  it('asks for a new QR every few seconds after a failure, not in a loop', async () => {
    const wrapper = mount(PhoneAccessDialog, { global: { plugins: [i18n] } })
    await flushPromises()
    await vi.advanceTimersByTimeAsync(100)
    expect(qrAsked).toBe(1)
    await vi.advanceTimersByTimeAsync(3000)
    expect(qrAsked).toBe(1)
    await vi.advanceTimersByTimeAsync(3000)
    expect(qrAsked).toBe(2)
    wrapper.unmount()
  })
})
