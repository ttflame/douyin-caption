const fallback = '/tasks'

export function safeReturnTo(value: string | null) {
  return value && value.startsWith('/') && !value.startsWith('//') ? value : fallback
}

export function saveReturnTo(value: string) {
  sessionStorage.setItem('dc_return_to', safeReturnTo(value))
}

export function consumeReturnTo() {
  const value = safeReturnTo(sessionStorage.getItem('dc_return_to'))
  sessionStorage.removeItem('dc_return_to')
  return value
}
