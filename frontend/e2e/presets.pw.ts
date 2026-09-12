import { expect, test } from '@playwright/test'

test('manages personal presets and clears only finished operation history', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1262, height: 698 })
  await page.addInitScript(() => {
    localStorage.setItem('dc_token', 'test-session')
    localStorage.setItem('dc_member', JSON.stringify({ id: 'owner', username: 'tester', displayName: '测试成员', role: 'member', active: true }))
  })
  const settings = {
    target_length_mode: 'follow_source', target_characters: 800,
    persona: { custom_instruction: '实战创作者' }, audience: { custom_instruction: '短视频创作者' },
    language_style: { custom_instruction: '自然口语' }, content_structure: { custom_instruction: '问题切入' },
    output_specification: { custom_instruction: '单人口播' }, hard_constraints: { custom_instruction: '不虚构数据' },
  }
  const preset = { id: 'preset-1', name: '跟随原文方案', settings, created_at: '2026-09-12T00:00:00Z', updated_at: '2026-09-12T00:00:00Z' }
  const operations = [
    { id: 'done', task_id: 'a', task_name: '已完成文案', kind: 'analysis', status: 'succeeded', created_at: '2026-09-12T00:00:00Z', started_at: '2026-09-12T00:00:00Z', completed_at: '2026-09-12T00:01:00Z' },
    { id: 'waiting', task_id: 'b', task_name: '排队中文案', kind: 'analysis', status: 'queued', created_at: '2026-09-12T00:02:00Z', started_at: null, completed_at: null },
  ]
  let updateBody: Record<string, unknown> | undefined
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '')
    const send = (body: unknown, status = 200) => route.fulfill({ status, json: body })
    if (path === '/operations/history' && route.request().method() === 'DELETE') {
      operations.splice(0, operations.length, ...operations.filter((item) => item.status === 'queued' || item.status === 'running'))
      return route.fulfill({ status: 204 })
    }
    if (path === '/operations') return send(operations)
    if (path === '/presets' && route.request().method() === 'GET') return send([preset])
    if (path === '/presets/preset-1' && route.request().method() === 'PATCH') {
      updateBody = route.request().postDataJSON()
      Object.assign(preset, { name: String(updateBody?.name), settings: updateBody?.settings, updated_at: new Date().toISOString() })
      return send(preset)
    }
    return send({}, 404)
  })

  await page.goto('/presets')
  await expect(page.getByRole('link', { name: '预设方案', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: /跟随原文方案/ })).toBeVisible()
  await expect(page.getByRole('button', { name: '跟随原文', exact: true })).toHaveClass(/active/)
  await page.getByLabel('语言风格').fill('自然口语，短句')
  await page.getByRole('button', { name: '保存预设', exact: true }).click()
  await expect.poll(() => updateBody?.settings).toMatchObject({ target_length_mode: 'follow_source' })

  await page.getByRole('button', { name: '任务中心', exact: true }).click()
  await expect(page.getByText('已完成文案')).toBeVisible()
  await expect(page.getByText('排队中文案')).toBeVisible()
  await page.getByRole('button', { name: '清除任务历史' }).click()
  await page.getByRole('button', { name: '确认清除' }).click()
  await expect(page.getByText('已完成文案')).toHaveCount(0)
  await expect(page.getByText('排队中文案')).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('presets-desktop.png'), fullPage: true })

  await page.getByRole('button', { name: '收起任务中心', exact: true }).click()
  await page.setViewportSize({ width: 390, height: 844 })
  await expect.poll(() => page.locator('.sidebar').evaluate((element) => element.getBoundingClientRect().right)).toBeLessThanOrEqual(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('presets-mobile.png'), fullPage: true })
})
