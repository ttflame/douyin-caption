export interface ClientEvent {
  eventType: 'api_start' | 'api_success' | 'api_timeout' | 'api_network_error' | 'api_http_error' | 'auth_expired' | 'window_error' | 'unhandled_rejection'
  stage: string
  requestId?: string
  attempt?: number
  method?: string
  path?: string
  durationMs?: number
  status?: number
  code?: string
  message?: string
  script?: string
  line?: number
}

const clean = (value: string | undefined, limit = 200) => value?.replace(/[\r\n\t]+/g, ' ').slice(0, limit)
const pathTemplate = (path: string | undefined) => path?.split('?')[0]?.replace(/[0-9a-f]{8}-[0-9a-f-]{27,}/gi, ':id')
const browserCategory = () => /Edg/i.test(navigator.userAgent) ? 'edge' : /Firefox/i.test(navigator.userAgent) ? 'firefox' : /Chrome|Chromium/i.test(navigator.userAgent) ? 'chromium' : /Safari/i.test(navigator.userAgent) ? 'safari' : 'other'
const platformCategory = () => /Android/i.test(navigator.userAgent) ? 'android' : /iPhone|iPad|iPod/i.test(navigator.userAgent) ? 'ios' : /Windows/i.test(navigator.userAgent) ? 'windows' : /Mac OS/i.test(navigator.userAgent) ? 'macos' : /Linux/i.test(navigator.userAgent) ? 'linux' : 'other'

export function reportClientEvent(event: ClientEvent) {
  if (event.path === '/client-events') return
  const base = (localStorage.getItem('dc_api_base') || import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')
  const token = localStorage.getItem('dc_token')
  if (!token) return
  const body = {
    event_type: event.eventType,
    stage: clean(event.stage, 60),
    request_id: clean(event.requestId, 80),
    attempt: event.attempt,
    method: clean(event.method, 10),
    path: pathTemplate(event.path),
    duration_ms: event.durationMs,
    status: event.status,
    code: clean(event.code, 80),
    message: clean(event.message),
    script: event.script ? clean(event.script.split('/').at(-1), 120) : undefined,
    line: event.line,
    route: location.pathname.slice(0, 200),
    browser: browserCategory(),
    platform: platformCategory(),
    viewport: `${innerWidth}x${innerHeight}`,
    online: navigator.onLine,
    visibility: document.visibilityState,
  }
  void fetch(`${base}/client-events`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
    keepalive: true,
  }).catch(() => {})
}

export function installClientTelemetry() {
  window.addEventListener('error', event => reportClientEvent({ eventType: 'window_error', stage: 'window', message: event.message, script: event.filename, line: event.lineno }))
  window.addEventListener('unhandledrejection', event => reportClientEvent({ eventType: 'unhandled_rejection', stage: 'window', message: event.reason instanceof Error ? event.reason.message : String(event.reason) }))
}
