import { expect, test } from '@playwright/test'

test('background queue survives navigation and reload without mixing task results', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1262, height: 698 })
  const member = { id: 'owner', username: 'tester', displayName: '测试成员', role: 'member', active: true }
  await page.addInitScript((value) => {
    localStorage.setItem('dc_token', 'test-session')
    localStorage.setItem('dc_member', JSON.stringify(value))
  }, member)
  const tasks = [
    { id: 'alpha', name: '文案 A', source_text: '第一篇原文', state: 'draft' },
    { id: 'beta', name: '文案 B', source_text: '第二篇原文', state: 'draft' },
  ]
  type Operation = { id: string; task_id: string; task_name: string; kind: string; status: string; created_at: string; started_at: string | null; completed_at: string | null; resource_id?: string; resource_type?: string }
  const operations: Operation[] = []
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '')
    const send = (body: unknown, status = 200) => route.fulfill({ status, json: body })
    if (path === '/operations') return send(operations)
    if (path === '/settings/provider') return send({}, 404)
    if (path === '/tasks') return send(tasks.map(task => ({ ...task, updated_at: new Date().toISOString() })))
    const parts = path.split('/')
    const task = tasks.find(item => item.id === parts[2])
    if (!task) return send({}, 404)
    if (parts[3] === 'analysis' && route.request().method() === 'POST') {
      const operation = { id: `job-${task.id}`, task_id: task.id, task_name: task.name, kind: 'analysis', status: 'queued', created_at: new Date().toISOString(), started_at: null, completed_at: null }
      operations.push(operation)
      return send(operation, 202)
    }
    if (parts[3] === 'analyses') return send(task.state === 'analysis_ready' ? [{ id: 'result-alpha', is_selected: true, payload: { content: '文案 A 的结构分析结果' } }] : [])
    if (parts.length > 3) return send([])
    return send({ ...task, updated_at: new Date().toISOString(), creative_settings: { target_characters: 800 } })
  })

  await page.goto('/workbench/alpha')
  await page.getByRole('button', { name: '开始结构分析' }).click()
  await expect(page.getByRole('region', { name: '任务队列' })).toBeVisible()
  await expect(page.getByRole('button', { name: '开始结构分析' })).toBeDisabled()
  operations[0]!.status = 'running'
  operations[0]!.started_at = new Date().toISOString()
  tasks[0]!.state = 'analyzing'
  await page.getByRole('link', { name: '系统设置', exact: true }).click()
  await expect(page.getByRole('heading', { name: '系统设置', exact: true })).toBeVisible()
  await page.reload()
  await page.getByRole('button', { name: '任务中心', exact: true }).click()
  await expect(page.getByText('结构分析 · 执行中')).toBeVisible({ timeout: 10000 })
  await page.goto('/workbench/beta')
  await page.getByRole('button', { name: '开始结构分析' }).click()
  await expect(page.getByText('结构分析 · 排队中')).toBeVisible()
  await expect(page.getByRole('heading', { name: '文案 B', exact: true })).toBeVisible()

  Object.assign(operations[0]!, { status: 'succeeded', completed_at: new Date().toISOString(), resource_id: 'result-alpha', resource_type: 'analysis' })
  tasks[0]!.state = 'analysis_ready'
  Object.assign(operations[1]!, { status: 'running', started_at: new Date().toISOString() })
  tasks[1]!.state = 'analyzing'
  await expect(page.getByText('结构分析 · 已完成')).toBeVisible({ timeout: 10000 })
  await expect(page.getByRole('heading', { name: '文案 B', exact: true })).toBeVisible()
  await expect(page.getByText('文案 A 的结构分析结果')).toHaveCount(0)
  await page.screenshot({ path: testInfo.outputPath('worker-desktop.png') })
  await page.getByRole('link', { name: '查看文案：文案 A', exact: true }).click()
  await expect(page.getByText('文案 A 的结构分析结果')).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  await expect.poll(() => page.locator('.sidebar').evaluate(element => element.getBoundingClientRect().right)).toBeLessThanOrEqual(0)
  await expect(page.getByRole('region', { name: '任务队列' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('worker-mobile.png') })
  await page.getByRole('button', { name: '收起任务中心', exact: true }).click()
  await expect(page.getByRole('region', { name: '任务队列' })).toHaveCount(0)
})
