import { expect, test, type Page } from '@playwright/test'

const task = { id: 'mobile', name: '人设故事', source_text: '待改写原文', state: 'suggestions_ready', updated_at: new Date().toISOString(), creative_settings: { target_characters: 800 } }
const suggestions = Array.from({ length: 7 }, (_, index) => ({ id: `s${index}`, title: `方案 ${index + 1}`, direction: `第 ${index + 1} 项优化方向`, priority: index < 4 ? 'primary' : 'optional', decision: 'pending', member_note: null }))

async function seedMobileSession(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem('dc_token', 'test-session')
    localStorage.setItem('dc_member', JSON.stringify({ id: 'owner', username: 'tester', displayName: '测试成员', role: 'member' }))
  })
}

test('submits one immutable selection snapshot after rapid mobile edits', async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true })
  const page = await context.newPage()
  await seedMobileSession(page)
  const operations: Record<string, unknown>[] = []
  const writes: { method: string; path: string; body: unknown }[] = []

  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '')
    const method = route.request().method()
    const send = (data: unknown, status = 200) => route.fulfill({ status, json: data })
    if (path === '/client-events') return route.fulfill({ status: 204 })
    if (path === '/operations') return send(operations)
    if (path === '/tasks/mobile') return send(task)
    if (path === '/tasks/mobile/versions' || path === '/tasks/mobile/locks') return send([])
    if (path === '/tasks/mobile/analyses') return send([{ id: 'analysis', is_selected: true, payload: { content: '结构分析' } }])
    if (path === '/tasks/mobile/suggestions' && method === 'GET') return send(suggestions)
    if (method !== 'GET') writes.push({ method, path, body: route.request().postDataJSON() })
    if (path === '/tasks/mobile/first-draft' && method === 'POST') {
      const operation = { id: 'draft-job', task_id: 'mobile', task_name: task.name, kind: 'first_draft', status: 'queued', created_at: new Date().toISOString() }
      operations.push(operation)
      return send(operation, 202)
    }
    return send({}, 404)
  })

  await page.goto('/workbench/mobile')
  const checkboxes = await page.getByRole('checkbox').all()
  for (const checkbox of checkboxes) await checkbox.check()
  await checkboxes[1]?.uncheck()
  await checkboxes[1]?.check()
  await checkboxes[5]?.uncheck()
  await page.getByPlaceholder('补充备注（可选）').first().fill('保留真实语气')
  await expect(page.getByText('已选择 6 项', { exact: true })).toBeVisible()
  expect(writes).toEqual([])

  const generate = page.getByRole('button', { name: '生成第一版', exact: true })
  await expect(generate).toBeEnabled()
  await generate.click()
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0]?.path).toBe('/tasks/mobile/first-draft')
  expect((writes[0]?.body as { suggestion_decisions: unknown[] }).suggestion_decisions).toHaveLength(7)
  expect((writes[0]?.body as { suggestion_decisions: { suggestion_id: string; selected: boolean; member_note: string | null }[] }).suggestion_decisions[0]).toEqual({ suggestion_id: 's0', selected: true, member_note: '保留真实语气' })
  expect((writes[0]?.body as { suggestion_decisions: { suggestion_id: string; selected: boolean }[] }).suggestion_decisions[5]?.selected).toBe(false)
  await expect(page.getByText('生成第一版 · 排队中')).toBeVisible()
  expect(await page.evaluate(() => Object.keys(sessionStorage).filter(key => key.startsWith('dc_suggestion_draft:')))).toEqual([])
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  await context.close()
})

test('restores the mobile selection after login expiry without auto-submitting', async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true })
  const page = await context.newPage()
  await seedMobileSession(page)
  let submissions = 0

  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '')
    const method = route.request().method()
    const send = (data: unknown, status = 200) => route.fulfill({ status, json: data })
    if (path === '/client-events') return route.fulfill({ status: 204 })
    if (path === '/auth/login') return send({ access_token: 'renewed', member: { id: 'owner', username: 'tester', display_name: '测试成员', role: 'member', is_active: true } })
    if (path === '/operations') return send([])
    if (path === '/tasks/mobile') return send(task)
    if (path === '/tasks/mobile/versions' || path === '/tasks/mobile/locks') return send([])
    if (path === '/tasks/mobile/analyses') return send([{ id: 'analysis', is_selected: true, payload: { content: '结构分析' } }])
    if (path === '/tasks/mobile/suggestions' && method === 'GET') return send(suggestions)
    if (path === '/tasks/mobile/first-draft') {
      submissions += 1
      if (submissions === 1) return send({ error: { code: 'unauthorized', message: 'expired' } }, 401)
      return send({ id: 'draft-job', task_id: 'mobile', task_name: task.name, kind: 'first_draft', status: 'queued', created_at: new Date().toISOString() }, 202)
    }
    return send({}, 404)
  })

  await page.goto('/workbench/mobile')
  await page.getByRole('checkbox').first().check()
  await page.getByPlaceholder('补充备注（可选）').first().fill('登录后仍保留')
  await page.getByRole('button', { name: '生成第一版', exact: true }).click()
  await expect(page).toHaveURL(/\/login\?expired=1/)
  await page.getByLabel('账号').fill('tester')
  await page.getByLabel('密码').fill('password')
  await page.getByRole('button', { name: '进入工作台' }).click()
  await expect(page).toHaveURL(/\/workbench\/mobile/)
  await expect(page.getByRole('checkbox').first()).toBeChecked()
  await expect(page.getByPlaceholder('补充备注（可选）').first()).toHaveValue('登录后仍保留')
  expect(submissions).toBe(1)
  await page.getByRole('button', { name: '生成第一版', exact: true }).click()
  await expect.poll(() => submissions).toBe(2)
  await context.close()
})
