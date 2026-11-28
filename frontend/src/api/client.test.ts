import { afterEach, describe, expect, it, vi } from 'vitest'

import { api, ApiError, lastHeard, reopenStreams, subscribe } from './client'

function answer(status: number, body: string) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(new Response(body, { status, statusText: 'Oops' })),
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('api client', () => {
  it('reads the error shape the API answers with', async () => {
    answer(429, JSON.stringify({ ok: false, type: 'flood_wait', message: 'Wait', retry_after: 7 }))
    const err = await api.get('/api/x').catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err).toMatchObject({ status: 429, type: 'flood_wait', message: 'Wait', retryAfter: 7 })
  })

  it('adds what Telegram said to the message', async () => {
    answer(
      502,
      JSON.stringify({
        ok: false,
        type: 'telegram_error',
        message: 'Refused',
        reason: 'CHANNEL_PRIVATE',
      }),
    )
    const err = await api.get('/api/channels/1/full').catch((e: unknown) => e)
    expect(err).toMatchObject({ type: 'telegram_error', message: 'Refused: CHANNEL_PRIVATE' })
  })

  it('turns a body that is not JSON into an ApiError too', async () => {
    answer(500, 'Internal Server Error')
    const err = await api.post('/api/apply').catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err).toMatchObject({ status: 500, type: 'http_error', message: 'Internal Server Error' })
  })

  it('returns the parsed body on success', async () => {
    answer(200, JSON.stringify({ ok: true }))
    expect(await api.get('/api/health')).toEqual({ ok: true })
  })
})

describe('event streams', () => {
  it('opens anew only the streams gone quiet', () => {
    vi.useFakeTimers()
    const opened: string[] = []
    const sources: { url: string; listeners: Record<string, () => void> }[] = []
    vi.stubGlobal(
      'EventSource',
      class {
        listeners: Record<string, () => void> = {}
        url: string
        constructor(url: string) {
          this.url = url
          opened.push(url)
          sources.push(this)
        }
        addEventListener(event: string, fn: () => void) {
          this.listeners[event] = fn
        }
        close() {}
      },
    )
    const closeAuth = subscribe('/auth', {})
    const closeSync = subscribe('/sync', {})
    vi.advanceTimersByTime(8000)
    sources[0]!.listeners.ping!() // the auth stream still pings; the sync one died quietly
    expect(Date.now() - lastHeard()).toBe(8000)
    reopenStreams(7000)
    expect(opened).toEqual(['/auth', '/sync', '/sync'])
    expect(Date.now() - lastHeard()).toBe(0)
    closeAuth()
    closeSync()
    reopenStreams()
    expect(opened).toHaveLength(3)
    vi.useRealTimers()
  })
})
