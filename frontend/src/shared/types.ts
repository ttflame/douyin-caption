export type Role = 'admin' | 'member'
export type TaskState = 'draft' | 'analyzing' | 'analysis_ready' | 'suggesting' | 'suggestions_ready' | 'generating' | 'editing' | 'revising' | 'finalized' | 'archived'
export type SuggestionPriority = 'primary' | 'optional'

export interface Member { id: string; username: string; displayName: string; role: Role; active: boolean; createdAt: string }
export interface CreativeSettings { targetLengthMode: 'fixed' | 'follow_source'; targetCharacters: number; persona: string; audience: string; languageStyle: string; contentStructure: string; outputSpecification: string; hardConstraints: string }
export interface AnalysisModule { id: string; title: string; finding: string; issue?: string }
export interface Suggestion { id: string; title: string; description: string; priority: SuggestionPriority; sourceModule: string; selected: boolean; note?: string }
export interface SuggestionDecisionInput { suggestionId: string; selected: boolean; memberNote: string | null }
export interface CreativePreset { id: string; name: string; settings: CreativeSettings; updatedAt: string }
export interface TextLock { id: string; text: string; sourceVersionId?: string; startOffset?: number; endOffset?: number }
export interface Version { id: string; kind: 'first_draft' | 'ai_revision' | 'manual_edit'; label: string; content: string; createdAt: string; parentId?: string; instruction?: string; isCurrentFinal?: boolean; validationStatus?: string }
export interface RewriteTask { id: string; name: string; sourceText: string; settings: CreativeSettings; state: TaskState; updatedAt: string; stableState?: TaskState; analysisId?: string; analysis: AnalysisModule[]; suggestions: Suggestion[]; versions: Version[]; locks: TextLock[]; finalVersionId?: string }
export interface ProviderSettings { configured: boolean; maskedKey: string; baseUrl: string; modelId: string; timeoutSeconds: number }
export type OperationStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'
export type OperationKind = 'analysis' | 'suggestions' | 'first_draft' | 'revision'
export interface AiOperation { id: string; taskId: string; taskName: string; kind: OperationKind; status: OperationStatus; createdAt: string; startedAt?: string; completedAt?: string; resourceType?: string; resourceId?: string; error?: { code?: string; message: string } }
