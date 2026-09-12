// @vitest-environment jsdom

import { beforeEach, describe, expect, it } from 'vitest'
import { clearSuggestionDraft, createSuggestionDraft, decisionSnapshot, loadSuggestionDraft, saveSuggestionDraft, suggestionDraftKey } from './suggestionDraft'
import type { Suggestion } from '../../shared/types'

const suggestions: Suggestion[] = [
  { id: 'one', title: '一', description: '一', priority: 'primary', sourceModule: 'analysis', selected: false },
  { id: 'two', title: '二', description: '二', priority: 'optional', sourceModule: 'analysis', selected: true, note: '服务端备注' },
]

describe('suggestion local draft', () => {
  beforeEach(() => sessionStorage.clear())

  it('keeps edits local and builds one complete normalized snapshot', () => {
    const draft = createSuggestionDraft('analysis-a', suggestions)
    draft.decisions.one.selected = true
    draft.decisions.one.memberNote = '  本地备注  '
    expect(decisionSnapshot(suggestions, draft)).toEqual([
      { suggestionId: 'one', selected: true, memberNote: '本地备注' },
      { suggestionId: 'two', selected: true, memberNote: '服务端备注' },
    ])
  })

  it('restores only matching member/task/analysis drafts and drops removed suggestions', () => {
    const key = suggestionDraftKey('member', 'task', 'analysis-a')
    const draft = createSuggestionDraft('analysis-a', suggestions)
    draft.decisions.one.selected = true
    draft.memberRequirements = '补充要求'
    saveSuggestionDraft(key, draft)

    const restored = createSuggestionDraft('analysis-a', [suggestions[0]!], loadSuggestionDraft(key))
    expect(restored.decisions).toEqual({ one: { selected: true, memberNote: '' } })
    expect(restored.memberRequirements).toBe('补充要求')
    expect(createSuggestionDraft('analysis-b', suggestions, restored).decisions.one?.selected).toBe(false)
    clearSuggestionDraft(key)
    expect(loadSuggestionDraft(key)).toBeNull()
  })
})
