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

export function subscribe(url: string, handlers: SseHandlers): () => void {
  const source = new EventSource(url)
  for (const [event, handler] of Object.entries(handlers)) {
    source.addEventListener(event, (e) => {
      handler(JSON.parse((e as MessageEvent<string>).data) as never)
    })
  }
  return () => source.close()
}
