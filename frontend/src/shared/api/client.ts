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

export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  if (token()) headers.set('Authorization', `Bearer ${token()}`)
  const response = await fetch(`${normalizedBase()}${path}`, { ...init, headers })
  if (response.status === 401) window.dispatchEvent(new CustomEvent('dc:unauthorized'))
  if (!response.ok) {
    let body: ApiErrorBody = {}
    try { body = await response.json() as ApiErrorBody } catch { /* Some gateway errors have no JSON body. */ }
    throw new ApiError(response.status, errorMessage(body, `请求失败 (${response.status})`), body.error?.code, body.error?.details)
  }
  if (response.status === 204) return undefined as T
  return await response.json() as T
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
