import type { ErrorBody } from './types'

/** An answer of the API's error shape: {ok: false, type, message, ...fields}. */
export class ApiError extends Error {
  readonly status: number
  /** What the UI acts on: flood_wait, apply_job_running, invalid_code… (TYPE of the backend's error class) */
  readonly type: string
  readonly retryAfter: number | null

  constructor(status: number, type: string, message: string, retryAfter: number | null = null) {
    super(message)
    this.status = status
    this.type = type
    this.retryAfter = retryAfter
  }
}

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  const response = await fetch(url, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const text = await response.text()
  const data = parseJson(text)
  if (!response.ok) {
    // The API always answers in its error shape; anything else (a proxy, a crash before the app) still becomes an
    // ApiError the views know how to show
    const err = data as Partial<ErrorBody> | null
    const message = err?.message ?? (text.trim() || response.statusText)
    throw new ApiError(
      response.status,
      err?.type ?? 'http_error',
      err?.reason ? `${message}: ${err.reason}` : message,
      err?.retry_after ?? null,
    )
  }
  return data as T
}

function parseJson(text: string): unknown {
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    return null
  }
}

export const api = {
  get: <T>(url: string) => request<T>('GET', url),
  post: <T>(url: string, body: unknown = {}) => request<T>('POST', url, body),
  put: <T>(url: string, body: unknown) => request<T>('PUT', url, body),
  patch: <T>(url: string, body: unknown) => request<T>('PATCH', url, body),
  del: <T>(url: string) => request<T>('DELETE', url),
}

export type SseHandlers = Record<string, (data: never) => void>

interface Stream {
  /** When it last said anything, pings included: quiet for long, it died on the way or the server is gone. */
  heard: number
  reopen: () => void
}

/** The event streams open now, each able to start over: after a phone's sleep any of them may be dead. */
const streams = new Set<Stream>()

/** When the quietest open stream last said anything (now, with none open). */
export function lastHeard(): number {
  let at = Date.now()
  for (const stream of streams) at = Math.min(at, stream.heard)
  return at
}

/** Opens anew the streams quiet for longer than `ms` (all of them with 0): the server answers, they don't. */
export function reopenStreams(ms = 0) {
  const now = Date.now()
  for (const stream of streams) if (now - stream.heard >= ms) stream.reopen()
}

/** Marks every stream as just heard: the server was found there by other means. */
export function heardNow() {
  for (const stream of streams) stream.heard = Date.now()
}

export function subscribe(url: string, handlers: SseHandlers): () => void {
  let source: EventSource
  const stream: Stream = { heard: Date.now(), reopen: () => (source.close(), open()) }

  function open() {
    stream.heard = Date.now()
    source = new EventSource(url)
    // The server pings every 3 s even when nothing happens
    source.addEventListener('ping', () => (stream.heard = Date.now()))
    // This phone was disconnected on the computer: back to the pairing screen at once
    source.addEventListener('revoked', () => {
      close()
      location.replace('/pair')
    })
    for (const [event, handler] of Object.entries(handlers)) {
      source.addEventListener(event, (e) => {
        // A server's "error" event shares its name with the browser's own one (a failed reconnect), which has no
        // data
        if (!(e instanceof MessageEvent)) return
        stream.heard = Date.now()
        handler(JSON.parse(e.data as string) as never)
      })
    }
  }

  function close() {
    source.close()
    streams.delete(stream)
  }

  open()
  streams.add(stream)
  return close
}
