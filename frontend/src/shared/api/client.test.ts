// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiRequest } from './client'

afterEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
})

describe('idempotent submit request policy', () => {
  it('retries a retryable response with the same body and logical request id', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response('{}', { status: 503 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ accepted: true }), { status: 202 }))
    vi.stubGlobal('fetch', fetchMock)
    const body = JSON.stringify({ fixed: true })

    await expect(apiRequest('/submit', { method: 'POST', body, retryPolicy: 'idempotent-submit', requestId: 'logical-request' })).resolves.toEqual({ accepted: true })

    expect(fetchMock).toHaveBeenCalledTimes(2)
    const first = fetchMock.mock.calls[0]?.[1]
    const second = fetchMock.mock.calls[1]?.[1]
    expect(first.body).toBe(body)
    expect(second.body).toBe(body)
    expect((first.headers as Headers).get('X-Request-ID')).toBe('logical-request')
    expect((second.headers as Headers).get('X-Request-ID')).toBe('logical-request')
    expect((first.headers as Headers).get('X-Request-Attempt')).toBe('1')
    expect((second.headers as Headers).get('X-Request-Attempt')).toBe('2')
  })

  it('aborts a pending attempt and releases it as a timeout error', async () => {
    vi.stubGlobal('fetch', vi.fn((_url, init: RequestInit) => new Promise((_resolve, reject) => {
      init.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
    })))

    await expect(apiRequest('/pending', { timeoutMs: 10 })).rejects.toMatchObject({ code: 'request_timeout' })
  })
})
