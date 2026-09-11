import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, fromCreativeSettings, mapAnalysis, toCreativeSettings } from './adapter'

afterEach(() => vi.unstubAllGlobals())

describe('provider response timeout', () => {
  it('saves only the timeout without transmitting credentials and reads it back', async () => {
    const fetchMock = vi.fn().mockImplementation(async () => new Response(JSON.stringify({
      base_url: 'https://api.example.com/v1', model_id: 'model', api_key_masked: '***', timeout_seconds: 300,
    }), { status: 200 }))
    vi.stubGlobal('localStorage', { getItem: () => null })
    vi.stubGlobal('fetch', fetchMock)
    expect((await api.saveProviderTimeout(300)).timeoutSeconds).toBe(300)
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/settings/provider', expect.objectContaining({
      method: 'PATCH', body: JSON.stringify({ timeout_seconds: 300 }),
    }))
    expect((await api.getProvider()).timeoutSeconds).toBe(300)
  })

  it('defaults to 240 seconds for a new connection', async () => {
    vi.stubGlobal('localStorage', { getItem: () => null })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 404 })))
    expect((await api.getProvider()).timeoutSeconds).toBe(240)
  })
})

describe('mapAnalysis', () => {
  it('preserves free-form analysis text without inventing modules', () => {
    const content = '1. 开头提出问题。\n2. 正文拆解原因。'
    expect(mapAnalysis({ content })).toEqual([{ id: 'analysis', title: '文案结构', finding: content }])
  })
  it('maps the seven named backend modules in stable order', () => {
    const result = mapAnalysis({
      content_overview: { theme: '主题', core_viewpoint: '观点', target_audience: '受众', expected_action: '行动' },
      structure_map: { segments: [{ segment_id: 's1', kind: 'hook', source_excerpt: '原文', purpose: '吸引注意' }] },
      paragraph_analysis: [{ segment_id: 's1', relationship: '递进', issues: ['略长'] }],
      expression_analysis: { persona_consistency: '稳定', language_style: '自然', spoken_fluency: '流畅', emotional_intensity: '适中', information_density: '适中', spoken_rhythm: '清楚' },
      content_highlights: [{ excerpt: '亮点', reason: '具体' }],
      problems_and_risks: [{ issue_id: 'i1', category: 'repetition', description: '重复', source_excerpt: '片段' }],
      conclusion: { summary: '总结', key_issue_ids: ['i1'] },
    })

    expect(result).toHaveLength(7)
    expect(result.map((item) => item.id)).toEqual(['content_overview', 'structure_map', 'paragraph_analysis', 'expression_analysis', 'content_highlights', 'problems_and_risks', 'conclusion'])
    expect(result[5]?.issue).toBe('重复')
  })
})

describe('creative settings mapping', () => {
  it('maps camelCase UI settings to nested snake_case API settings and back', () => {
    const input = {
      targetLengthMode: 'follow_source' as const,
      targetCharacters: 500,
      persona: '创作者',
      audience: '新手',
      languageStyle: '自然口语',
      contentStructure: '递进',
      outputSpecification: '短句',
      hardConstraints: '不虚构',
    }

    const apiValue = toCreativeSettings(input)
    expect(apiValue.target_length_mode).toBe('follow_source')
    expect(apiValue.target_characters).toBe(500)
    expect(apiValue.language_style.custom_instruction).toBe('自然口语')
    expect(fromCreativeSettings(apiValue)).toEqual(input)
  })
})

describe('high-value workflow endpoints', () => {
  it('generates an idempotency key when randomUUID is unavailable on HTTP pages', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: 'operation', status: 'queued' }), { status: 200, headers: { 'content-type': 'application/json' } }))
    vi.stubGlobal('localStorage', { getItem: () => null })
    vi.stubGlobal('crypto', { getRandomValues: (bytes: Uint8Array) => bytes.fill(7) })
    vi.stubGlobal('fetch', fetchMock)

    await api.analyze('task')

    const headers = fetchMock.mock.calls[0]?.[1]?.headers as Headers
    const key = headers.get('Idempotency-Key')
    expect(key).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
  })

  it('copies a task through the dedicated endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: 'copied', name: '副本', state: 'draft', source_text: '正文', creative_settings: toCreativeSettings({ ...api.defaultSettings }), created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', finalized_at: null }), { status: 200, headers: { 'content-type': 'application/json' } }))
    vi.stubGlobal('localStorage', { getItem: () => null })
    vi.stubGlobal('fetch', fetchMock)

    const copied = await api.copyTask('source')

    expect(copied.id).toBe('copied')
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/tasks/source/copy', expect.objectContaining({ method: 'POST' }))
  })

  it('sends snake_case identifiers and returns unified diff text', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ left_version_id: 'left', right_version_id: 'right', diff: '-旧句\n+新句\n' }), { status: 200, headers: { 'content-type': 'application/json' } }))
    vi.stubGlobal('localStorage', { getItem: () => null })
    vi.stubGlobal('fetch', fetchMock)

    const diff = await api.compareVersions('task', 'left', 'right')

    expect(diff).toContain('+新句')
    expect(JSON.parse(fetchMock.mock.calls[0]?.[1]?.body as string)).toEqual({ left_version_id: 'left', right_version_id: 'right' })
  })

  it('regenerates a version from the latest accepted suggestions', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: 'operation', status: 'queued' }), { status: 202, headers: { 'content-type': 'application/json' } }))
    vi.stubGlobal('localStorage', { getItem: () => null })
    vi.stubGlobal('fetch', fetchMock)

    await api.regenerateFromSuggestions('task', 'version', 'analysis', '保持克制')

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/tasks/task/revisions', expect.objectContaining({ method: 'POST' }))
    expect(JSON.parse(fetchMock.mock.calls[0]?.[1]?.body as string)).toEqual({
      parent_version_id: 'version',
      scope: 'suggestions',
      instruction: '保持克制',
      analysis_id: 'analysis',
      selection_start: null,
      selection_end: null,
    })
  })
})
