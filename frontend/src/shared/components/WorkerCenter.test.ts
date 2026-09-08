// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/vue'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import WorkerCenter from './WorkerCenter.vue'
import { api } from '../api/adapter'
import { useQueueStore } from '../stores/queue'
import type { AiOperation } from '../types'

vi.mock('../api/adapter', () => ({ api: { listOperations: vi.fn(), cancelOperation: vi.fn(), retryOperation: vi.fn() } }))
vi.mock('../stores/session', () => ({ useSessionStore: () => ({ member: { id: 'owner' } }) }))
afterEach(() => { cleanup(); vi.clearAllMocks() })

it('retains the queue across routes, shows completion and cancels waiting work', async () => {
  const row: AiOperation = { id: 'job', taskId: 'a', taskName: '原文 A', kind: 'analysis', status: 'running', createdAt: '2026-09-07T00:00:00Z', startedAt: new Date().toISOString() }
  const waiting: AiOperation = { ...row, id: 'waiting', taskId: 'b', taskName: '原文 B', status: 'queued', startedAt: undefined }
  vi.mocked(api.listOperations).mockResolvedValue([row, waiting])
  const pinia = createPinia()
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/settings', component: { template: '<div>Settings</div>' } },
    { path: '/workbench/:id', component: { template: '<div>Workbench</div>' } },
  ] })
  await router.push('/workbench/a')
  const view = render(WorkerCenter, { global: { plugins: [pinia, router] } })
  const queue = useQueueStore(pinia)
  await waitFor(() => expect(queue.active).toHaveLength(2))
  await fireEvent.click(screen.getByRole('button', { name: '任务中心' }))
  await router.push('/settings')
  expect(screen.getByText('原文 A')).toBeTruthy()
  vi.mocked(api.cancelOperation).mockResolvedValue({ ...waiting, status: 'cancelled' })
  await fireEvent.click(screen.getByRole('button', { name: '取消排队：原文 B' }))
  await waitFor(() => expect(queue.active).toHaveLength(1))
  vi.mocked(api.listOperations).mockResolvedValue([{ ...row, status: 'succeeded' }, { ...waiting, status: 'cancelled' }])
  await queue.refresh()
  await fireEvent.click(screen.getByRole('link', { name: '查看文案：原文 A' }))
  await waitFor(() => expect(router.currentRoute.value.path).toBe('/workbench/a'))
  expect(queue.updates.a?.status).toBe('succeeded')
  view.unmount()
  expect(queue.items).toEqual([])
})
