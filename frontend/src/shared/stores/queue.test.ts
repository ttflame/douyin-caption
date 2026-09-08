// @vitest-environment jsdom
import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { api } from '../api/adapter'
import { useQueueStore } from './queue'
import { useTaskStore } from './tasks'
import type { AiOperation, RewriteTask } from '../types'

vi.mock('../api/adapter', () => ({ api: { listOperations: vi.fn(), getTask: vi.fn(), cancelOperation: vi.fn(), retryOperation: vi.fn() } }))
const operation = (status: AiOperation['status']): AiOperation => ({ id: 'job', taskId: 'a', taskName: 'A', kind: 'analysis', status, createdAt: '2026-09-07T00:00:00Z' })
const deferred = <T,>() => { let resolve!: (value: T) => void; const promise = new Promise<T>((done) => { resolve = done }); return { promise, resolve } }

beforeEach(() => { setActivePinia(createPinia()); vi.clearAllMocks() })
afterEach(() => { useQueueStore().stop(); vi.useRealTimers() })

it('keeps submitted work when an older polling response arrives late', async () => {
  const queue = useQueueStore()
  const pending = deferred<AiOperation[]>()
  vi.mocked(api.listOperations).mockReturnValue(pending.promise)
  const refreshing = queue.refresh()
  await queue.submit(async () => operation('queued'))
  pending.resolve([])
  await refreshing
  expect(queue.active.map(item => item.id)).toEqual(['job'])
})

it('recovers active work and tracks completion for its original task', async () => {
  const queue = useQueueStore()
  vi.mocked(api.listOperations).mockResolvedValueOnce([operation('running')]).mockResolvedValueOnce([operation('succeeded')])
  await queue.refresh()
  expect(queue.active).toHaveLength(1)
  await queue.refresh()
  expect(queue.active).toHaveLength(0)
  expect(queue.updates.a?.status).toBe('succeeded')
  expect(queue.notice?.taskId).toBe('a')
})

it('does not leak late queue responses across logout', async () => {
  const queue = useQueueStore()
  const pending = deferred<AiOperation[]>()
  vi.mocked(api.listOperations).mockReturnValue(pending.promise)
  const refreshing = queue.refresh()
  queue.stop()
  pending.resolve([operation('running')])
  await refreshing
  expect(queue.items).toEqual([])
})

it('does not put a completed task into a different workbench', async () => {
  const tasks = useTaskStore()
  const task = (id: string) => ({ id, name: id, state: 'draft' }) as RewriteTask
  vi.mocked(api.getTask).mockResolvedValueOnce(task('a'))
  await tasks.loadOne('a')
  const pending = deferred<RewriteTask>()
  vi.mocked(api.getTask).mockReturnValueOnce(pending.promise).mockResolvedValueOnce(task('b'))
  const refreshing = tasks.refreshCurrent('a')
  await tasks.loadOne('b')
  pending.resolve({ ...task('a'), state: 'analysis_ready' })
  await refreshing
  expect(tasks.current?.id).toBe('b')
})

it('ignores a stale page load after navigation to another task', async () => {
  const tasks = useTaskStore()
  const pending = deferred<RewriteTask>()
  vi.mocked(api.getTask).mockReturnValueOnce(pending.promise).mockResolvedValueOnce({ id: 'b' } as RewriteTask)
  const loading = tasks.loadOne('a')
  await tasks.loadOne('b')
  pending.resolve({ id: 'a' } as RewriteTask)
  await loading
  expect(tasks.current?.id).toBe('b')
})
