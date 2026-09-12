import type { Suggestion, SuggestionDecisionInput } from '../../shared/types'

export interface SuggestionDraft {
  analysisId: string
  decisions: Record<string, { selected: boolean; memberNote: string }>
  memberRequirements: string
}

export const suggestionDraftKey = (memberId: string, taskId: string, analysisId: string) => `dc_suggestion_draft:${memberId}:${taskId}:${analysisId}`

export function createSuggestionDraft(analysisId: string, suggestions: Suggestion[], saved?: SuggestionDraft | null): SuggestionDraft {
  const compatible = saved?.analysisId === analysisId ? saved.decisions : {}
  return {
    analysisId,
    decisions: Object.fromEntries(suggestions.map(item => [item.id, compatible[item.id] ?? { selected: item.selected, memberNote: item.note ?? '' }])),
    memberRequirements: saved?.analysisId === analysisId ? saved.memberRequirements : '',
  }
}

export function decisionSnapshot(suggestions: Suggestion[], draft: SuggestionDraft): SuggestionDecisionInput[] {
  return suggestions.map(item => {
    const decision = draft.decisions[item.id] ?? { selected: item.selected, memberNote: item.note ?? '' }
    return { suggestionId: item.id, selected: decision.selected, memberNote: decision.memberNote.trim() || null }
  })
}

export function loadSuggestionDraft(key: string): SuggestionDraft | null {
  try { return JSON.parse(sessionStorage.getItem(key) || 'null') as SuggestionDraft | null } catch { return null }
}

export function saveSuggestionDraft(key: string, draft: SuggestionDraft) {
  try { sessionStorage.setItem(key, JSON.stringify(draft)) } catch { /* Storage may be unavailable in private mode. */ }
}

export function clearSuggestionDraft(key: string) {
  try { sessionStorage.removeItem(key) } catch { /* Storage may be unavailable in private mode. */ }
}
