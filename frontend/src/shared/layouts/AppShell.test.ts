// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import AppShell from './AppShell.vue'

const session = vi.hoisted(() => ({
  member: { displayName: 'Administrator', role: 'admin' }, logout: vi.fn(),
}))
vi.mock('../stores/session', () => ({ useSessionStore: () => session }))
vi.mock('../components/WorkerCenter.vue', () => ({ default: { template: '<div />' } }))

beforeEach(() => {
  localStorage.clear()
  session.logout.mockClear()
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }
})
afterEach(cleanup)

async function setup() {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/tasks', component: { template: '<div>Tasks</div>' } },
    { path: '/login', component: { template: '<div>Login</div>' } },
  ] })
  await router.push('/tasks')
  await router.isReady()
  const view = render(AppShell, { global: { plugins: [router] } })
  return { ...view, router }
}

it('requires confirmation before clearing the session and navigating away', async () => {
  const { router } = await setup()
  await fireEvent.click(screen.getByRole('button', { name: '退出登录' }))
  expect(session.logout).not.toHaveBeenCalled()
  expect(screen.getByRole('dialog').hasAttribute('open')).toBe(true)
  await fireEvent.click(screen.getByRole('button', { name: '取消' }))
  expect(session.logout).not.toHaveBeenCalled()
  expect(router.currentRoute.value.path).toBe('/tasks')
  await fireEvent.click(screen.getByRole('button', { name: '退出登录' }))
  await fireEvent.click(screen.getByRole('button', { name: '确认退出' }))
  expect(session.logout).toHaveBeenCalledTimes(1)
  await waitFor(() => expect(router.currentRoute.value.path).toBe('/login'))
})

it('remembers sidebar collapse and retains named navigation links', async () => {
  const view = await setup()
  await fireEvent.click(screen.getByRole('button', { name: '收起侧边栏' }))
  expect(view.container.querySelector('.app-shell')?.classList.contains('sidebar-collapsed')).toBe(true)
  expect(screen.getByRole('link', { name: '成员管理' }).getAttribute('title')).toBe('成员管理')
  await waitFor(() => expect(localStorage.getItem('dc_sidebar_collapsed')).toBe('true'))
  view.unmount()
  await setup()
  expect(screen.getByRole('button', { name: '展开侧边栏' })).toBeTruthy()
})
