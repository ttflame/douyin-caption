// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/vue'
import PresetManagementPage from './PresetManagementPage.vue'
import { api, defaultSettings } from '../../shared/api/adapter'
import type { CreativePreset } from '../../shared/types'

const saved: CreativePreset = {
  id: 'preset-1',
  name: '跟随原文方案',
  settings: { ...defaultSettings, targetLengthMode: 'follow_source' },
  updatedAt: '2026-09-12T00:00:00Z',
}

vi.mock('../../shared/api/adapter', async (load) => {
  const actual = await load<typeof import('../../shared/api/adapter')>()
  return {
    ...actual,
    api: {
      ...actual.api,
      listPresets: vi.fn(),
      createPreset: vi.fn(),
      updatePreset: vi.fn(),
      deletePreset: vi.fn(),
    },
  }
})

afterEach(() => { cleanup(); vi.clearAllMocks() })

it('edits a saved preset explicitly and retains the follow-source length mode', async () => {
  vi.mocked(api.listPresets).mockResolvedValue([saved])
  vi.mocked(api.updatePreset).mockResolvedValue({ ...saved, settings: { ...saved.settings, languageStyle: '更口语' } })
  render(PresetManagementPage)
  await screen.findByRole('button', { name: /跟随原文方案/ })
  expect(screen.getByRole('button', { name: '保存预设' }).hasAttribute('disabled')).toBe(true)
  await fireEvent.update(screen.getByLabelText('语言风格'), '更口语')
  await fireEvent.click(screen.getByRole('button', { name: '保存预设' }))
  await waitFor(() => expect(api.updatePreset).toHaveBeenCalledWith(
    'preset-1',
    '跟随原文方案',
    expect.objectContaining({ targetLengthMode: 'follow_source', languageStyle: '更口语' }),
  ))
})
