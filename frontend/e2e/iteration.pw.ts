import { expect, test } from '@playwright/test'

test('keeps selected suggestions and sentence locks through repeated generation', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.addInitScript(() => {
    localStorage.setItem('dc_token', 'test-session')
    localStorage.setItem('dc_member', JSON.stringify({ id: 'owner', username: 'tester', displayName: '测试成员', role: 'member' }))
  })
  const task = { id: 'alpha', name: '口播文案', source_text: '这是一篇待优化的原文。', state: 'suggestions_ready', updated_at: new Date().toISOString(), creative_settings: { target_characters: 800 } }
  const suggestions = Array.from({ length: 5 }, (_, index) => ({ id: `s${index}`, title: `方案 ${index + 1}`, direction: `第 ${index + 1} 项具体优化方向`, priority: index < 3 ? 'primary' : 'optional', decision: 'pending', member_note: null as string | null }))
  const versions: { id: string; kind: string; content: string; created_at: string; parent_id: string | null }[] = []
  const locks: { id: string; text: string; source_version_id: string; start_offset: number; end_offset: number }[] = []
  const operations: { id: string; task_id: string; task_name: string; kind: string; status: string; created_at: string; completed_at?: string; resource_type?: string; resource_id?: string }[] = []
  let revisionParent = ''
  const revisionScopes: string[] = []
  function complete(resourceType: string, resourceId: string, state: string) {
    Object.assign(operations.at(-1)!, { status: 'succeeded', resource_type: resourceType, resource_id: resourceId, completed_at: new Date().toISOString() })
    task.state = state
  }
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '')
    const method = route.request().method()
    const send = (data: unknown, status = 200) => route.fulfill({ status, json: data })
    if (path === '/operations') return send(operations)
    if (path === '/tasks/alpha') return send(task)
    if (path === '/tasks/alpha/versions') return send(versions)
    if (path === '/tasks/alpha/analyses') return send([{ id: 'analysis', is_selected: true, payload: { content: '结构分析' } }])
    if (path === '/tasks/alpha/locks') return send(locks)
    if (path === '/tasks/alpha/suggestions' && method === 'GET') return send(suggestions)
    if (path.startsWith('/tasks/alpha/suggestions/') && method === 'PATCH') {
      await new Promise(resolve => setTimeout(resolve, 250))
      Object.assign(suggestions.find(item => item.id === path.split('/').at(-1))!, route.request().postDataJSON())
      return send({})
    }
    if (path.endsWith('/manual-edit')) {
      const payload = route.request().postDataJSON()
      const version = { id: `v${versions.length + 1}`, kind: 'manual_edit', content: payload.content, parent_id: path.split('/')[4]!, created_at: new Date().toISOString() }
      versions.push(version)
      return send(version)
    }
    if (path.endsWith('/locks') && method === 'POST') {
      const payload = route.request().postDataJSON()
      const versionId = path.split('/')[4]!
      const version = versions.find(item => item.id === versionId)!
      const lock = { id: `lock${locks.length + 1}`, text: Array.from(version.content).slice(payload.start_offset, payload.end_offset).join(''), source_version_id: versionId, ...payload }
      locks.push(lock)
      return send(lock)
    }
    if (path.startsWith('/tasks/alpha/locks/') && method === 'DELETE') {
      locks.splice(locks.findIndex(item => item.id === path.split('/').at(-1)), 1)
      return route.fulfill({ status: 204 })
    }
    if (method === 'POST' && ['/tasks/alpha/suggestions', '/tasks/alpha/first-draft', '/tasks/alpha/revisions'].includes(path)) {
      const kind = path.endsWith('suggestions') ? 'suggestions' : path.endsWith('first-draft') ? 'first_draft' : 'revision'
      if (kind === 'revision') {
        const payload = route.request().postDataJSON()
        revisionParent = payload.parent_version_id
        revisionScopes.push(payload.scope)
      }
      const operation = { id: `job${operations.length + 1}`, task_id: 'alpha', task_name: task.name, kind, status: 'queued', created_at: new Date().toISOString() }
      operations.push(operation)
      return send(operation, 202)
    }
    return send({}, 404)
  })
  await page.goto('/workbench/alpha')
  await page.getByRole('checkbox').first().check()
  await page.getByRole('checkbox').nth(1).check()
  await expect(page.getByText('已固定 2 项', { exact: true })).toBeVisible()
  await expect.poll(() => suggestions.filter(item => item.decision === 'accepted').length).toBe(2)
  await page.screenshot({ path: testInfo.outputPath('suggestions-mobile-multiselect.png'), fullPage: true })
  await page.setViewportSize({ width: 723, height: 698 })
  await page.getByRole('button', { name: '继续优化方案', exact: true }).click()
  await expect.poll(() => operations.length).toBe(1)
  expect(suggestions[0]!.decision).toBe('accepted')
  expect(suggestions[1]!.decision).toBe('accepted')
  suggestions.slice(1).forEach(item => { item.title = `新${item.title}` })
  complete('suggestions', 'analysis', 'suggestions_ready')
  await expect(page.getByText('新方案 2', { exact: true })).toBeVisible({ timeout: 10000 })
  await expect(page.getByRole('checkbox').first()).toBeChecked()
  await page.getByRole('button', { name: '收起任务中心', exact: true }).click()
  await page.screenshot({ path: testInfo.outputPath('continued-suggestions.png') })
  await page.getByRole('button', { name: '生成第一版', exact: true }).click()
  await expect.poll(() => operations.length).toBe(2)
  versions.push({ id: 'v1', kind: 'first_draft', parent_id: null, content: '🙂开头说明问题。中间这句需要优化。结尾保留承诺。', created_at: new Date().toISOString() })
  complete('version', 'v1', 'editing')
  await expect(page.getByRole('button', { name: '锁定句子：🙂开头说明问题。', exact: true })).toBeVisible({ timeout: 10000 })
  await page.getByRole('button', { name: '收起任务中心', exact: true }).click()
  await page.getByRole('button', { name: '锁定句子：🙂开头说明问题。', exact: true }).click()
  await expect(page.locator('.locked-sentence')).toHaveCount(1)
  expect(locks[0]!.text).toBe('🙂开头说明问题。')
  await page.getByRole('button', { name: '编辑', exact: true }).click()
  await page.getByRole('textbox', { name: '成品文案编辑器' }).fill('🙂开头说明问题。补充一句。中间这句需要优化。结尾保留承诺。')
  await page.getByRole('button', { name: '按句锁定', exact: true }).click()
  await page.getByRole('button', { name: '锁定句子：补充一句。', exact: true }).click()
  await expect(page.locator('.locked-sentence')).toHaveCount(2)
  expect(locks[1]!.source_version_id).toBe('v2')
  expect(locks[1]!.text).toBe('补充一句。')
  await page.getByRole('button', { name: '再次生成', exact: true }).click()
  await expect.poll(() => operations.length).toBe(3)
  expect(revisionParent).toBe('v2')
  versions.push({ id: 'v3', kind: 'ai_revision', parent_id: 'v2', content: '新的结构更自然。补充一句。🙂开头说明问题。结尾更加简洁。', created_at: new Date().toISOString() })
  complete('version', 'v3', 'editing')
  await expect(page.getByRole('button', { name: '锁定句子：新的结构更自然。', exact: true })).toBeVisible({ timeout: 10000 })
  await page.getByRole('button', { name: '收起任务中心', exact: true }).click()
  await expect(page.locator('.locked-sentence')).toHaveCount(2)
  await page.getByRole('button', { name: '优化方案' }).click()
  await page.getByRole('checkbox').first().uncheck()
  await expect.poll(() => suggestions[0]!.decision).toBe('rejected')
  await page.getByRole('button', { name: '按当前方案生成新版本', exact: true }).click()
  await expect.poll(() => operations.length).toBe(4)
  expect(revisionParent).toBe('v3')
  expect(revisionScopes.at(-1)).toBe('suggestions')
  versions.push({ id: 'v4', kind: 'ai_revision', parent_id: 'v3', content: '按方案生成的新稿。补充一句。🙂开头说明问题。', created_at: new Date().toISOString() })
  complete('version', 'v4', 'editing')
  await expect(page.getByRole('button', { name: '锁定句子：按方案生成的新稿。', exact: true })).toBeVisible({ timeout: 10000 })
  await page.getByRole('button', { name: '收起任务中心', exact: true }).click()
  await expect(page.locator('.locked-sentence')).toHaveCount(2)
  await page.setViewportSize({ width: 1262, height: 698 })
  await page.screenshot({ path: testInfo.outputPath('locked-sentences-desktop.png') })
  await page.reload()
  await expect(page.locator('.locked-sentence')).toHaveCount(2)
  await page.setViewportSize({ width: 390, height: 844 })
  await expect.poll(() => page.locator('.sidebar').evaluate(element => element.getBoundingClientRect().right)).toBeLessThanOrEqual(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('locked-sentences-mobile.png') })
  await page.getByRole('button', { name: '优化方案' }).click()
  await page.screenshot({ path: testInfo.outputPath('suggestion-regeneration-mobile.png'), fullPage: true })
  await page.getByRole('button', { name: '成品修改' }).click()
  await page.getByRole('button', { name: '取消保留：补充一句。', exact: true }).click()
  await expect(page.locator('.locked-sentence')).toHaveCount(1)
})
