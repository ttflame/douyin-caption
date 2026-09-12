import { reportClientEvent } from './telemetry'

export interface ApiErrorBody { error?: { code?: string; message?: string; details?: unknown }; detail?: string | { msg?: string }[] }

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details?: unknown
  constructor(status: number, message: string, code = 'request_failed', details?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }
}

export interface ApiRequestOptions extends RequestInit {
  timeoutMs?: number
  retryPolicy?: 'idempotent-submit'
  requestId?: string
  stage?: string
}

const normalizedBase = () => {
  const configured = localStorage.getItem('dc_api_base') || import.meta.env.VITE_API_BASE_URL || '/api/v1'
  return configured.replace(/\/$/, '')
}

function token() { return localStorage.getItem('dc_token') ?? '' }

function errorMessage(body: ApiErrorBody, fallback: string) {
  if (body.error?.message) return body.error.message
  if (typeof body.detail === 'string') return body.detail
  if (Array.isArray(body.detail)) return body.detail.map((item) => item.msg).filter(Boolean).join('；') || fallback
  return fallback
}

export function generateRequestId() {
  if (typeof globalThis.crypto?.randomUUID === 'function') return globalThis.crypto.randomUUID()
  const bytes = new Uint8Array(16)
  if (typeof globalThis.crypto?.getRandomValues === 'function') globalThis.crypto.getRandomValues(bytes)
  else for (let index = 0; index < bytes.length; index += 1) bytes[index] = Math.floor(Math.random() * 256)
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

const wait = (milliseconds: number) => new Promise(resolve => globalThis.setTimeout(resolve, milliseconds))
const retryableStatus = (status: number) => status === 408 || status === 429 || status >= 500

export async function apiRequest<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  const { timeoutMs = 15_000, retryPolicy, requestId = generateRequestId(), stage = 'api_request', ...init } = options
  const headers = new Headers(init.headers)
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  if (token()) headers.set('Authorization', `Bearer ${token()}`)
  headers.set('X-Request-ID', requestId)
  const attempts = retryPolicy === 'idempotent-submit' ? 3 : 1
  let finalError: unknown

  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    const controller = new AbortController()
    const abort = () => controller.abort()
    if (init.signal?.aborted) controller.abort()
    else init.signal?.addEventListener('abort', abort, { once: true })
    const timeout = globalThis.setTimeout(() => controller.abort(), timeoutMs)
    const attemptHeaders = new Headers(headers)
    attemptHeaders.set('X-Request-Attempt', String(attempt))
    const started = performance.now()
    reportClientEvent({ eventType: 'api_start', stage, requestId, attempt, method: init.method || 'GET', path })
    try {
      const response = await fetch(`${normalizedBase()}${path}`, { ...init, headers: attemptHeaders, signal: controller.signal })
      const durationMs = Math.round(performance.now() - started)
      if (response.ok) {
        reportClientEvent({ eventType: 'api_success', stage, requestId, attempt, method: init.method || 'GET', path, durationMs })
        if (response.status === 204) return undefined as T
        return await response.json() as T
      }
      if (response.status === 401) {
        reportClientEvent({ eventType: 'auth_expired', stage: 'auth_expired', requestId, attempt, method: init.method || 'GET', path, durationMs, status: 401 })
        window.dispatchEvent(new CustomEvent('dc:unauthorized', { detail: { requestId } }))
      }
      let body: ApiErrorBody = {}
      try { body = await response.json() as ApiErrorBody } catch { /* Gateways may return plain text. */ }
      finalError = new ApiError(response.status, errorMessage(body, `请求失败 (${response.status})`), body.error?.code, body.error?.details)
      reportClientEvent({ eventType: 'api_http_error', stage, requestId, attempt, method: init.method || 'GET', path, durationMs, status: response.status, code: body.error?.code })
      if (attempt === attempts || !retryableStatus(response.status)) throw finalError
    } catch (reason) {
      if (reason instanceof ApiError) throw reason
      const timedOut = controller.signal.aborted && !init.signal?.aborted
      finalError = timedOut
        ? new ApiError(408, '提交超时，当前选择已保留，请重试', 'request_timeout')
        : new ApiError(0, '网络连接失败，当前选择已保留，请重试', 'network_error')
      reportClientEvent({ eventType: timedOut ? 'api_timeout' : 'api_network_error', stage, requestId, attempt, method: init.method || 'GET', path, durationMs: Math.round(performance.now() - started) })
      if (attempt === attempts || init.signal?.aborted) throw finalError
    } finally {
      globalThis.clearTimeout(timeout)
      init.signal?.removeEventListener('abort', abort)
    }
    await wait(attempt === 1 ? 500 : 1_500)
  }
  throw finalError
}

export async function apiDownload(path: string): Promise<{ blob: Blob; filename?: string }> {
  const headers = new Headers()
  if (token()) headers.set('Authorization', `Bearer ${token()}`)
  const response = await fetch(`${normalizedBase()}${path}`, { headers })
  if (!response.ok) {
    let body: ApiErrorBody = {}
    try { body = await response.json() as ApiErrorBody } catch { /* Export proxy may return plain text. */ }
    throw new ApiError(response.status, errorMessage(body, `导出失败 (${response.status})`), body.error?.code)
  }
  const disposition = response.headers.get('content-disposition')
  const filename = disposition?.match(/filename="?([^";]+)"?/i)?.[1]
  return { blob: await response.blob(), filename }
}

export function setApiBase(base: string) { localStorage.setItem('dc_api_base', base.replace(/\/$/, '')) }
