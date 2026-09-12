import { apiDownload, ApiError, apiRequest } from './client'
import type { AiOperation, AnalysisModule, CreativePreset, CreativeSettings, Member, ProviderSettings, RewriteTask, Suggestion, SuggestionDecisionInput, TaskState, TextLock, Version } from '../types'

type Json = Record<string, unknown>
let uuidFallbackCounter = 0

function formatUuid(bytes: Uint8Array) {
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

function generateIdempotencyKey() {
  const cryptoApi = globalThis.crypto
  if (typeof cryptoApi?.randomUUID === 'function') {
    try {
      return cryptoApi.randomUUID()
    } catch {
      // Some browsers expose randomUUID but reject it outside secure contexts.
    }
  }

  const bytes = new Uint8Array(16)
  let hasRandomBytes = false
  if (typeof cryptoApi?.getRandomValues === 'function') {
    try {
      cryptoApi.getRandomValues(bytes)
      hasRandomBytes = true
    } catch {
      // Fall through to the non-crypto fallback.
    }
  }
  if (!hasRandomBytes) {
    const timestamp = Date.now()
    const counter = uuidFallbackCounter++
    for (let index = 0; index < bytes.length; index += 1) bytes[index] = Math.floor(Math.random() * 256)
    for (let index = 0; index < 6; index += 1) bytes[index] ^= (timestamp >>> (index * 8)) & 0xff
    for (let index = 0; index < 4; index += 1) bytes[12 + index] ^= (counter >>> (index * 8)) & 0xff
  }
  return formatUuid(bytes)
}

const idempotencyHeaders = () => ({ 'Idempotency-Key': generateIdempotencyKey() })

export const defaultSettings: CreativeSettings = {
  targetLengthMode: 'fixed',
  targetCharacters: 800,
  persona: '一位有实战经验的内容创作者，用亲历者视角分享方法',
  audience: '想提升短视频表达能力，但没有系统方法的创作者',
  languageStyle: '自然口语，短句，克制，不喊口号',
  contentStructure: '问题切入，拆解误区，给出方法，结尾回扣观点',
  outputSpecification: '适合单人口播，段落清楚，开头快速进入主题',
  hardConstraints: '不虚构数据，不使用夸张承诺',
}

function object(value: unknown): Json { return value && typeof value === 'object' ? value as Json : {} }
function text(value: unknown, fallback = '') { return typeof value === 'string' ? value : fallback }
function bool(value: unknown) { return Boolean(value) }
function array(value: unknown) { return Array.isArray(value) ? value : [] }
function custom(value: unknown) { return text(object(value).custom_instruction) }

function mapProvider(raw: unknown): ProviderSettings {
  const value = object(raw)
  return { configured: true, maskedKey: text(value.api_key_masked), baseUrl: text(value.base_url), modelId: text(value.model_id), timeoutSeconds: Number(value.timeout_seconds) || 240 }
}

function mapMember(raw: unknown): Member {
  const value = object(raw)
  return { id: text(value.id), username: text(value.username), displayName: text(value.display_name), role: value.role === 'admin' ? 'admin' : 'member', active: bool(value.is_active), createdAt: text(value.created_at) }
}

export function fromCreativeSettings(raw: unknown): CreativeSettings {
  const value = object(raw)
  return { targetLengthMode: value.target_length_mode === 'follow_source' ? 'follow_source' : 'fixed', targetCharacters: Number(value.target_characters) || defaultSettings.targetCharacters, persona: custom(value.persona), audience: custom(value.audience), languageStyle: custom(value.language_style), contentStructure: custom(value.content_structure), outputSpecification: custom(value.output_specification), hardConstraints: custom(value.hard_constraints) }
}

export function toCreativeSettings(value: CreativeSettings) {
  return {
    target_length_mode: value.targetLengthMode,
    target_characters: value.targetCharacters,
    persona: { custom_instruction: value.persona },
    audience: { custom_instruction: value.audience },
    language_style: { custom_instruction: value.languageStyle },
    content_structure: { custom_instruction: value.contentStructure },
    output_specification: { custom_instruction: value.outputSpecification },
    hard_constraints: { custom_instruction: value.hardConstraints },
  }
}

function mapTask(raw: unknown): RewriteTask {
  const value = object(raw)
  return {
    id: text(value.id), name: text(value.name), sourceText: text(value.source_text), settings: value.creative_settings ? fromCreativeSettings(value.creative_settings) : { ...defaultSettings, targetCharacters: 0 },
    state: text(value.state, 'draft') as TaskState, updatedAt: text(value.updated_at), analysis: [], suggestions: [], versions: [], locks: [], finalVersionId: value.finalized_at ? '' : undefined,
  }
}

function mapVersion(raw: unknown, index = 0): Version {
  const value = object(raw); const kind = text(value.kind, 'ai_revision') as Version['kind']
  return { id: text(value.id), parentId: text(value.parent_id) || undefined, kind, label: kind === 'first_draft' ? '第一版成品' : kind === 'manual_edit' ? `手工修改 ${index}` : `AI 修改 ${index}`, content: text(value.content), instruction: text(value.instruction) || undefined, createdAt: text(value.created_at), isCurrentFinal: bool(value.is_current_final), validationStatus: text(value.validation_status) }
}

function mapLock(raw: unknown): TextLock {
  const value = object(raw)
  return { id: text(value.id), sourceVersionId: text(value.source_version_id), text: text(value.text), startOffset: Number(value.start_offset), endOffset: Number(value.end_offset) }
}

export function mapAnalysis(raw: unknown): AnalysisModule[] {
  const content = text(object(raw).content)
  if (content) return [{ id: 'analysis', title: '文案结构', finding: content }]
  const root = object(raw); const values = array(root.modules ?? root.analysis)
  if (values.length) return values.map((item, index) => { const value = object(item); return { id: text(value.id, `analysis-${index}`), title: text(value.title, text(value.name, `分析项 ${index + 1}`)), finding: text(value.finding, text(value.summary)), issue: text(value.issue, text(value.problem)) || undefined } })
  const overview = object(root.content_overview)
  const structure = array(object(root.structure_map).segments).map((item) => { const value = object(item); return `${text(value.kind)}：${text(value.purpose)}` }).filter((value) => value !== '：').join('；')
  const paragraphs = array(root.paragraph_analysis).map((item) => { const value = object(item); return `${text(value.relationship)}${array(value.issues).length ? `，${array(value.issues).map(String).join('、')}` : ''}` }).filter(Boolean).join('；')
  const expression = object(root.expression_analysis)
  const highlights = array(root.content_highlights).map((item) => { const value = object(item); return `${text(value.excerpt)}：${text(value.reason)}` }).filter((value) => value !== '：').join('；')
  const risks = array(root.problems_and_risks).map((item) => text(object(item).description)).filter(Boolean)
  const conclusion = object(root.conclusion)
  return [
    { id: 'content_overview', title: '内容概览', finding: [text(overview.theme), text(overview.core_viewpoint), text(overview.target_audience)].filter(Boolean).join('；') || '未返回内容概览' },
    { id: 'structure_map', title: '结构地图', finding: structure || '未识别出明确结构段落' },
    { id: 'paragraph_analysis', title: '段落关系', finding: paragraphs || '段落衔接未发现明显问题' },
    { id: 'expression_analysis', title: '表达分析', finding: [text(expression.language_style), text(expression.spoken_fluency), text(expression.information_density), text(expression.spoken_rhythm)].filter(Boolean).join('；') || '未返回表达分析' },
    { id: 'content_highlights', title: '内容亮点', finding: highlights || '原文中没有明显亮点段落' },
    { id: 'problems_and_risks', title: '问题与风险', finding: risks.length ? risks.join('；') : '未发现明确风险', issue: risks.length ? risks.join('；') : undefined },
    { id: 'conclusion', title: '分析结论', finding: text(conclusion.summary, '未返回分析结论') },
  ]
}

function mapSuggestions(raw: unknown): Suggestion[] {
  const root = object(raw); const values = array(root.suggestions ?? raw)
  return values.map((item, index) => { const value = object(item); return { id: text(value.id, `suggestion-${index}`), title: text(value.title), description: text(value.direction, text(value.description, text(value.reason))), priority: value.priority === 'optional' ? 'optional' : 'primary', sourceModule: array(value.analysis_issue_ids).map(String).join('、') || text(value.source_module, text(value.problem)), selected: value.decision === 'accepted' || value.selected === true, note: text(value.member_note) } })
}

function mapPreset(raw: unknown): CreativePreset { const value = object(raw); return { id: text(value.id), name: text(value.name), settings: fromCreativeSettings(value.settings), updatedAt: text(value.updated_at) } }

function mapOperation(raw: unknown): AiOperation {
  const value = object(raw); const error = object(value.error)
  const errorCode = text(value.error_code, text(error.code))
  const errorMessage = text(value.error_message, text(error.message))
  return { id: text(value.id), taskId: text(value.task_id), taskName: text(value.task_name, '文案任务'), kind: text(value.kind) as AiOperation['kind'], status: text(value.status, 'queued') as AiOperation['status'], createdAt: text(value.created_at), startedAt: text(value.started_at) || undefined, completedAt: text(value.completed_at) || undefined, resourceType: text(value.resource_type) || undefined, resourceId: text(value.resource_id) || undefined, error: errorCode || errorMessage ? { code: errorCode || undefined, message: errorMessage || 'AI 操作失败' } : undefined }
}

async function submitOperation(path: string, body: unknown) {
  return mapOperation(await apiRequest(path, { method: 'POST', headers: idempotencyHeaders(), body: JSON.stringify(body), retryPolicy: 'idempotent-submit', stage: path.includes('first-draft') ? 'first_draft_submit' : path.includes('revisions') ? 'suggestion_regeneration_submit' : 'suggestions_submit' }))
}

const decisionPayload = (items: SuggestionDecisionInput[]) => items.map(item => ({ suggestion_id: item.suggestionId, selected: item.selected, member_note: item.memberNote }))

export const api = {
  defaultSettings,
  async login(username: string, password: string) { const raw = object(await apiRequest('/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) })); return { token: text(raw.access_token), member: mapMember(raw.member) } },
  async currentMember() { return mapMember(await apiRequest('/auth/me')) },
  async listTasks(archived = false) { return array(await apiRequest(`/tasks?archived=${archived}`)).map(mapTask) },
  async getTask(taskId: string) { const [detail, versionRows, analysisRows, suggestionRows, lockRows] = await Promise.all([apiRequest(`/tasks/${taskId}`), apiRequest(`/tasks/${taskId}/versions`), apiRequest(`/tasks/${taskId}/analyses`), apiRequest(`/tasks/${taskId}/suggestions`), apiRequest(`/tasks/${taskId}/locks`)]); const task = mapTask(detail); const versions = array(versionRows).map(mapVersion); const analyses = array(analysisRows).map(object); const selectedAnalysis = analyses.find((item) => item.is_selected === true) ?? analyses.at(-1); task.analysisId = selectedAnalysis ? text(selectedAnalysis.id) : undefined; task.analysis = selectedAnalysis ? mapAnalysis(selectedAnalysis.payload) : []; task.suggestions = mapSuggestions(suggestionRows); task.versions = versions; task.locks = array(lockRows).map(mapLock); task.finalVersionId = versions.find((item) => item.isCurrentFinal)?.id; return task },
  async createTask(payload: { name: string; sourceText: string; settings: CreativeSettings }) { return mapTask(await apiRequest('/tasks', { method: 'POST', body: JSON.stringify({ name: payload.name, source_text: payload.sourceText, creative_settings: toCreativeSettings(payload.settings) }) })) },
  async copyTask(taskId: string) { return mapTask(await apiRequest(`/tasks/${taskId}/copy`, { method: 'POST' })) },
  async listPresets() { return array(await apiRequest('/presets')).map(mapPreset) },
  async createPreset(name: string, settings: CreativeSettings) { return mapPreset(await apiRequest('/presets', { method: 'POST', body: JSON.stringify({ name, settings: toCreativeSettings(settings) }) })) },
  async updatePreset(presetId: string, name: string, settings: CreativeSettings) { return mapPreset(await apiRequest(`/presets/${presetId}`, { method: 'PATCH', body: JSON.stringify({ name, settings: toCreativeSettings(settings) }) })) },
  async deletePreset(presetId: string) { await apiRequest(`/presets/${presetId}`, { method: 'DELETE' }) },
  async archiveTask(taskId: string) { return mapTask(await apiRequest(`/tasks/${taskId}/archive`, { method: 'POST' })) },
  async restoreTask(taskId: string) { return mapTask(await apiRequest(`/tasks/${taskId}/restore`, { method: 'POST' })) },
  async updateDraft(task: RewriteTask) { return mapTask(await apiRequest(`/tasks/${task.id}`, { method: 'PATCH', body: JSON.stringify({ name: task.name, source_text: task.sourceText, creative_settings: toCreativeSettings(task.settings) }) })) },
  async getProvider(): Promise<ProviderSettings> { try { return mapProvider(await apiRequest('/settings/provider')) } catch (reason) { if (reason instanceof ApiError && reason.status === 404) return { configured: false, maskedKey: '', baseUrl: 'https://api.openai.com/v1', modelId: '', timeoutSeconds: 240 }; throw reason } },
  async saveProvider(value: ProviderSettings & { apiKey?: string }) { if (!value.apiKey) throw new ApiError(400, '保存连接设置时需要重新输入 API Key', 'api_key_required'); return mapProvider(await apiRequest('/settings/provider', { method: 'PUT', body: JSON.stringify({ api_key: value.apiKey, base_url: value.baseUrl, model_id: value.modelId, timeout_seconds: value.timeoutSeconds }) })) },
  async saveProviderTimeout(timeoutSeconds: number) { return mapProvider(await apiRequest('/settings/provider', { method: 'PATCH', body: JSON.stringify({ timeout_seconds: timeoutSeconds }) })) },
  async deleteProvider() { await apiRequest('/settings/provider', { method: 'DELETE' }) },
  async changePassword(currentPassword: string, newPassword: string) { await apiRequest('/auth/change-password', { method: 'POST', body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }) }) },
  async testProvider(value: { apiKey?: string; baseUrl?: string; modelId?: string; timeoutSeconds?: number }) { return object(await apiRequest('/settings/provider/test', { method: 'POST', body: JSON.stringify({ api_key: value.apiKey || null, base_url: value.baseUrl || null, model_id: value.modelId || null, timeout_seconds: value.timeoutSeconds ?? null }) })) },
  async listMembers() { return array(await apiRequest('/admin/members')).map(mapMember) },
  async createMember(value: { username: string; displayName: string; password: string }) { return mapMember(await apiRequest('/admin/members', { method: 'POST', body: JSON.stringify({ username: value.username, display_name: value.displayName, password: value.password, role: 'member' }) })) },
  async updateMember(member: Member) { return mapMember(await apiRequest(`/admin/members/${member.id}`, { method: 'PATCH', body: JSON.stringify({ display_name: member.displayName, is_active: member.active }) })) },
  async listOperations() { return array(await apiRequest('/operations')).map(mapOperation) },
  async clearOperationHistory() { await apiRequest('/operations/history', { method: 'DELETE' }) },
  async cancelOperation(id: string) { return mapOperation(await apiRequest(`/operations/${id}/cancel`, { method: 'POST' })) },
  async retryOperation(id: string) { return submitOperation(`/operations/${id}/retry`, {}) },
  async analyze(taskId: string) { return submitOperation(`/tasks/${taskId}/analysis`, {}) },
  async suggest(taskId: string, analysisId: string, decisions: SuggestionDecisionInput[]) { return submitOperation(`/tasks/${taskId}/suggestions`, { analysis_id: analysisId, suggestion_decisions: decisionPayload(decisions), member_context: '' }) },
  async decideSuggestion(taskId: string, suggestionId: string, selected: boolean, note?: string) { await apiRequest(`/tasks/${taskId}/suggestions/${suggestionId}`, { method: 'PATCH', body: JSON.stringify({ decision: selected ? 'accepted' : 'rejected', member_note: note || null }) }) },
  async firstDraft(taskId: string, analysisId: string, decisions: SuggestionDecisionInput[], memberRequirements = '') { return submitOperation(`/tasks/${taskId}/first-draft`, { analysis_id: analysisId, suggestion_decisions: decisionPayload(decisions), member_requirements: memberRequirements }) },
  async regenerateFromSuggestions(taskId: string, parentVersionId: string, analysisId: string, decisions: SuggestionDecisionInput[], memberRequirements = '') { return submitOperation(`/tasks/${taskId}/revisions`, { parent_version_id: parentVersionId, scope: 'suggestions', instruction: memberRequirements.trim() || '按当前优化方案重新生成', analysis_id: analysisId, suggestion_decisions: decisionPayload(decisions), selection_start: null, selection_end: null }) },
  async revise(taskId: string, payload: { parentVersionId: string; instruction: string; selection?: { start: number; end: number } }) { return submitOperation(`/tasks/${taskId}/revisions`, { parent_version_id: payload.parentVersionId, instruction: payload.instruction, scope: payload.selection ? 'selection' : 'full', selection_start: payload.selection?.start ?? null, selection_end: payload.selection?.end ?? null }) },
  async manualEdit(taskId: string, versionId: string, content: string) { return mapVersion(await apiRequest(`/tasks/${taskId}/versions/${versionId}/manual-edit`, { method: 'POST', body: JSON.stringify({ content, instruction: '成员手工编辑' }) })) },
  async compareVersions(taskId: string, leftVersionId: string, rightVersionId: string) { const value = object(await apiRequest(`/tasks/${taskId}/versions/compare`, { method: 'POST', body: JSON.stringify({ left_version_id: leftVersionId, right_version_id: rightVersionId }) })); return text(value.diff) },
  async createLock(taskId: string, versionId: string, start: number, end: number) { return mapLock(await apiRequest(`/tasks/${taskId}/versions/${versionId}/locks`, { method: 'POST', body: JSON.stringify({ start_offset: start, end_offset: end, note: null }) })) },
  async deleteLock(taskId: string, lockId: string) { await apiRequest(`/tasks/${taskId}/locks/${lockId}`, { method: 'DELETE' }) },
  async finalize(taskId: string, versionId: string) { return mapVersion(await apiRequest(`/tasks/${taskId}/versions/${versionId}/finalize`, { method: 'POST' })) },
  async exportTask(taskId: string, format: 'txt' | 'md') { const result = await apiDownload(`/tasks/${taskId}/export?format=${format}`); const url = URL.createObjectURL(result.blob); const link = document.createElement('a'); link.href = url; link.download = result.filename ?? `${taskId}.${format}`; document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(url) },
}
