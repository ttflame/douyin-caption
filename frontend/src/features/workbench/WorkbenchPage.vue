<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Check, ChevronRight, CircleAlert, Download, FileCheck2, FileText, GitCompareArrows, History, LockKeyhole, Pencil, Play, Sparkles, Trash2, X } from 'lucide-vue-next'
import { api } from '../../shared/api/adapter'
import StatePanel from '../../shared/components/StatePanel.vue'
import UiButton from '../../shared/components/UiButton.vue'
import UiField from '../../shared/components/UiField.vue'
import { useSessionStore } from '../../shared/stores/session'
import { useTaskStore } from '../../shared/stores/tasks'
import { useQueueStore } from '../../shared/stores/queue'
import type { Suggestion, Version } from '../../shared/types'
import TextEditor from './TextEditor.vue'
import { locateLocks, sentenceSelections, type SentenceSelection } from './sentences'
import type { RewriteTask } from '../../shared/types'

type TabId = 'source' | 'analysis' | 'suggestions' | 'editing' | 'final'
const route = useRoute()
const router = useRouter()
const store = useTaskStore()
const queue = useQueueStore()
const session = useSessionStore()
const tab = ref<TabId>('source')
const operation = ref('')
const operationError = ref('')
const selectedVersionId = ref('')
const editorText = ref('')
const revisionInstruction = ref('')
const firstDraftRequirements = ref('')
const savingSuggestionIds = ref(new Set<string>())
const selectionRange = ref<{ start: number; end: number } | null>(null)
const draftDirty = ref(false)
const compareLeft = ref('')
const compareRight = ref('')
const compareDiff = ref('')
const comparing = ref(false)
const showDiff = ref(false)
const task = computed(() => store.current)
const activeOperation = computed(() => queue.active.find(item => item.taskId === task.value?.id))
const aiBusy = computed(() => !!activeOperation.value || ['analyzing', 'suggesting', 'generating', 'revising'].includes(task.value?.state ?? ''))
const selectedVersion = computed(() => task.value?.versions.find((item) => item.id === selectedVersionId.value) ?? task.value?.versions.at(-1))
const hasFirstDraft = computed(() => Boolean(task.value?.versions.some((item) => item.kind === 'first_draft')))
const selectedSuggestions = computed(() => task.value?.suggestions.filter((item) => item.selected).length ?? 0)
const allSuggestionsFixed = computed(() => !!task.value?.suggestions.length && selectedSuggestions.value === task.value.suggestions.length)
const suggestionsSaving = computed(() => savingSuggestionIds.value.size > 0)
const allSentencesFixed = computed(() => {
  const sentences = sentenceSelections(editorText.value, task.value?.locks ?? [], selectedVersion.value?.id).filter(item => item.text)
  return sentences.length > 0 && sentences.every(sentence => sentence.parts.every(part => part.locked))
})
const finalVersion = computed(() => task.value?.versions.find((item) => item.id === task.value?.finalVersionId))
const autosaveKey = computed(() => `dc_draft:${session.member?.id ?? 'unknown'}:${task.value?.id ?? 'unknown'}:${selectedVersion.value?.id ?? 'none'}`)
const tabs: { id: TabId; label: string }[] = [{ id: 'source', label: '原文' }, { id: 'analysis', label: '结构分析' }, { id: 'suggestions', label: '优化方案' }, { id: 'editing', label: '成品修改' }, { id: 'final', label: '定稿' }]

function allowed(id: TabId) { if (id === 'source') return true; if (id === 'analysis') return Boolean(task.value?.analysis.length); if (id === 'suggestions') return Boolean(task.value?.suggestions.length); if (id === 'editing') return Boolean(task.value?.versions.length); return Boolean(task.value?.finalVersionId || task.value?.versions.length) }
function selectVersion(version: Version) { selectedVersionId.value = version.id; editorText.value = version.content; draftDirty.value = false }
function operationMessage(reason: unknown) { return reason instanceof Error ? reason.message : '操作未完成，当前内容已保留，可以重试。' }

async function run(kind: 'analysis' | 'suggestions' | 'draft' | 'regeneration' | 'revision') {
  if (!task.value || aiBusy.value || operation.value || (kind === 'regeneration' && suggestionsSaving.value)) return
  const taskId = task.value.id
  const analysisId = task.value.analysisId
  const snapshot = task.value
  const parent = selectedVersion.value
  let parentVersionId = parent?.id
  const content = editorText.value
  const instruction = revisionInstruction.value.trim() || '继续优化未锁定的部分，让表达更自然、逻辑更清晰。保留所有锁定句，位置可随文章结构调整。'
  const selection = selectionRange.value ?? undefined
  const requirements = firstDraftRequirements.value
  operation.value = kind
  operationError.value = ''
  try {
    if (kind === 'revision' && parent) parentVersionId = (await saveEditedVersion(snapshot, parent, content)).id
    if (kind === 'analysis') await queue.submit(() => api.analyze(taskId))
    if (kind === 'suggestions') await queue.submit(() => api.suggest(taskId, analysisId))
    if (kind === 'draft') await queue.submit(() => api.firstDraft(taskId, analysisId, requirements))
    if (kind === 'regeneration' && parentVersionId) { const versionId = parentVersionId; await queue.submit(() => api.regenerateFromSuggestions(taskId, versionId, analysisId, requirements)) }
    if (kind === 'revision' && parentVersionId) { const versionId = parentVersionId; await queue.submit(() => api.revise(taskId, { parentVersionId: versionId, instruction, selection })) }
  } catch (reason) { operationError.value = operationMessage(reason) }
  finally { operation.value = '' }
}

watch(() => queue.updates[String(route.params.id)], async (completed) => {
  if (!completed || task.value?.id !== completed.taskId) return
  const taskId = completed.taskId
  try {
    await store.refreshCurrent(taskId)
    if (task.value?.id !== taskId || String(route.params.id) !== taskId) return
    if (completed.status === 'succeeded') {
      if (completed.kind === 'analysis') tab.value = 'analysis'
      else if (completed.kind === 'suggestions') tab.value = 'suggestions'
      else if (!draftDirty.value) {
        const version = task.value.versions.find(item => item.id === completed.resourceId)
        if (version) selectVersion(version)
        tab.value = 'editing'
        revisionInstruction.value = ''; selectionRange.value = null
      }
    } else if (completed.error) operationError.value = completed.error.message
  } catch (reason) { operationError.value = operationMessage(reason) }
})

// A reload can fetch the document just before its first queue poll reports completion.
watch([() => task.value?.state, () => queue.items], async () => {
  const current = task.value
  if (!current || activeOperation.value || !['analyzing', 'suggesting', 'generating', 'revising'].includes(current.state)) return
  const latest = queue.items.find(item => item.taskId === current.id)
  if (!latest || latest.status === 'queued' || latest.status === 'running') return
  try { await store.refreshCurrent(current.id) }
  catch (reason) { operationError.value = operationMessage(reason) }
})

async function decideSuggestion(item: Suggestion) {
  if (!task.value || aiBusy.value || savingSuggestionIds.value.has(item.id)) return
  const taskId = task.value.id
  savingSuggestionIds.value = new Set(savingSuggestionIds.value).add(item.id)
  try { await api.decideSuggestion(taskId, item.id, item.selected, item.note) }
  catch (reason) { operationError.value = operationMessage(reason); await store.refreshCurrent(taskId).catch(() => {}) }
  finally { const next = new Set(savingSuggestionIds.value); next.delete(item.id); savingSuggestionIds.value = next }
}
async function saveEditedVersion(snapshot: RewriteTask, parent: Version, content: string) {
  if (content === parent.content) return parent
  if (locateLocks(content, snapshot.locks, parent.id).length !== snapshot.locks.length) throw new Error('编辑内容改动了保留句，请先取消对应锁定。')
  const oldKey = `dc_draft:${session.member?.id ?? 'unknown'}:${snapshot.id}:${parent.id}`
  const version = await api.manualEdit(snapshot.id, parent.id, content)
  snapshot.versions.push(version)
  localStorage.removeItem(oldKey)
  if (task.value?.id === snapshot.id && selectedVersion.value?.id === parent.id) selectVersion(version)
  return version
}
async function saveManual() {
  if (!task.value || !selectedVersion.value || !draftDirty.value || aiBusy.value || operation.value) return
  operation.value = 'manual'; operationError.value = ''
  try { await saveEditedVersion(task.value, selectedVersion.value, editorText.value) }
  catch (reason) { operationError.value = operationMessage(reason) }
  finally { operation.value = '' }
}
async function addLock(payload: { text: string; start: number; end: number }) {
  if (!task.value || !selectedVersion.value || aiBusy.value || operation.value) return
  const snapshot = task.value
  const parent = selectedVersion.value
  const content = editorText.value
  operation.value = 'lock'; operationError.value = ''
  try {
    const version = await saveEditedVersion(snapshot, parent, content)
    snapshot.locks.push(await api.createLock(snapshot.id, version.id, payload.start, payload.end))
  } catch (reason) { operationError.value = operationMessage(reason) }
  finally { operation.value = '' }
}
async function toggleSentence(sentence: SentenceSelection) {
  if (!sentence.lockIds.length) { await addLock(sentence); return }
  if (!task.value || aiBusy.value || operation.value) return
  const snapshot = task.value
  operation.value = 'lock'; operationError.value = ''
  try {
    for (const id of sentence.lockIds) {
      await api.deleteLock(snapshot.id, id)
      snapshot.locks = snapshot.locks.filter(item => item.id !== id)
    }
  } catch (reason) { operationError.value = operationMessage(reason) }
  finally { operation.value = '' }
}
function startLocal(payload: { text: string; start: number; end: number }) { selectionRange.value = { start: payload.start, end: payload.end }; revisionInstruction.value = `只修改选中的“${payload.text.slice(0, 24)}${payload.text.length > 24 ? '…' : ''}”` }
async function removeLock(lockId: string) { await toggleSentence({ text: '', start: 0, end: 0, lockIds: [lockId] }) }
async function finalize() { if (!task.value || !selectedVersion.value) return; operationError.value = ''; try { const version = await api.finalize(task.value.id, selectedVersion.value.id); task.value.versions = task.value.versions.map((item) => ({ ...item, isCurrentFinal: item.id === version.id })); task.value.finalVersionId = version.id; task.value.state = 'finalized'; tab.value = 'final' } catch (reason) { operationError.value = operationMessage(reason) } }
async function exportFinal(format: 'txt' | 'md') { if (!task.value) return; try { await api.exportTask(task.value.id, format) } catch (reason) { operationError.value = operationMessage(reason) } }
async function compareVersions() { if (!task.value || !compareLeft.value || !compareRight.value || compareLeft.value === compareRight.value) return; comparing.value = true; operationError.value = ''; try { compareDiff.value = await api.compareVersions(task.value.id, compareLeft.value, compareRight.value); showDiff.value = true } catch (reason) { operationError.value = operationMessage(reason) } finally { comparing.value = false } }

onMounted(async () => { await store.loadOne(String(route.params.id)); if (task.value) { const latest = task.value.versions.at(-1); if (latest) selectVersion(latest); if (task.value.versions.length > 1) { compareLeft.value = task.value.versions.at(-2)?.id ?? ''; compareRight.value = latest?.id ?? '' } if (task.value.state === 'finalized') tab.value = 'final'; else if (latest) tab.value = 'editing'; else if (task.value.suggestions.length) tab.value = 'suggestions'; else if (task.value.analysis.length) tab.value = 'analysis' } })
</script>

<template>
  <div class="workbench-page">
    <div v-if="store.loading" class="workbench-loading"><span class="skeleton block wide" /><span class="skeleton stage-line" /><span class="skeleton work-area" /></div>
    <StatePanel v-else-if="store.error || !task" :icon="CircleAlert" title="无法打开任务" :description="store.error || '任务不存在或你没有访问权限。'"><UiButton :icon="ArrowLeft" @click="router.push('/tasks')">返回任务列表</UiButton></StatePanel>
    <template v-else>
      <header class="workbench-header"><div><button class="text-back" type="button" @click="router.push('/tasks')"><ArrowLeft :size="16" />任务列表</button><h1>{{ task.name }}</h1></div><div class="header-meta"><span>{{ task.settings.targetCharacters }} 字</span><span v-if="task.finalVersionId" class="final-mark"><Check :size="14" />已定稿</span></div></header>
      <nav class="stage-nav" aria-label="任务阶段"><button v-for="(item, index) in tabs" :key="item.id" type="button" :class="{ active: tab === item.id, complete: allowed(item.id) && tab !== item.id }" :disabled="!allowed(item.id)" @click="tab = item.id"><span>{{ index + 1 }}</span>{{ item.label }}<ChevronRight v-if="index < tabs.length - 1" :size="15" /></button></nav>
      <div v-if="operationError" class="inline-alert error operation-alert" role="alert">{{ operationError }}</div>
      <div v-if="aiBusy" class="inline-alert operation-alert" role="status"><span>{{ activeOperation?.status === 'queued' ? '排队中' : '后台执行中' }}</span><UiButton size="small" :icon="History" @click="queue.expanded = true">查看任务</UiButton></div>
      <div class="workbench-grid">
        <fieldset class="workbench-controls" :disabled="aiBusy || !!operation">
        <main class="workbench-main">
          <section v-if="tab === 'source'" class="stage-content"><div class="stage-heading"><div><h2>原始文案</h2><p>{{ task.sourceText.length }} 字</p></div><div class="heading-actions"><UiButton v-if="task.state === 'draft'" :icon="Pencil" @click="router.push(`/tasks/${task.id}/edit`)">编辑草稿</UiButton><UiButton variant="primary" :icon="Play" :loading="operation === 'analysis'" @click="run('analysis')">开始结构分析</UiButton></div></div><div class="source-document">{{ task.sourceText }}</div></section>
          <section v-else-if="tab === 'analysis'" class="stage-content"><div class="stage-heading"><div><h2>结构分析</h2></div><UiButton variant="primary" :icon="Sparkles" :loading="operation === 'suggestions'" @click="run('suggestions')">生成优化方案</UiButton></div><div class="analysis-list"><article v-for="item in task.analysis" :key="item.id"><div><h3>{{ item.title }}</h3><p>{{ item.finding }}</p></div><p v-if="item.issue" class="analysis-issue">{{ item.issue }}</p></article></div></section>
          <section v-else-if="tab === 'suggestions'" class="stage-content">
            <div class="stage-heading suggestions-heading">
              <div><h2>选择优化方案</h2><p>已固定 {{ selectedSuggestions }} 项</p></div>
              <div class="heading-actions"><UiButton :icon="Sparkles" :loading="operation === 'suggestions'" :disabled="hasFirstDraft || allSuggestionsFixed" @click="run('suggestions')">继续优化方案</UiButton><UiButton variant="primary" :icon="FileText" :loading="operation === (hasFirstDraft ? 'regeneration' : 'draft')" :disabled="suggestionsSaving || (hasFirstDraft && !selectedVersion)" @click="run(hasFirstDraft ? 'regeneration' : 'draft')">{{ hasFirstDraft ? '按当前方案生成新版本' : '生成第一版' }}</UiButton></div>
            </div>
            <div class="suggestion-groups"><section v-for="priority in (['primary', 'optional'] as const)" :key="priority"><h3>{{ priority === 'primary' ? '优先优化' : '可选优化' }}</h3><label v-for="item in task.suggestions.filter((value) => value.priority === priority)" :key="item.id" class="suggestion-row" :class="{ 'suggestion-fixed': item.selected }"><input v-model="item.selected" type="checkbox" :disabled="savingSuggestionIds.has(item.id)" @change="decideSuggestion(item)" /><span class="custom-check"><Check :size="14" /></span><span><span class="suggestion-title">{{ item.title }}<LockKeyhole v-if="item.selected" :size="13" aria-label="已固定" /></span><small>{{ item.description }}</small><input v-model="item.note" class="suggestion-note" type="text" placeholder="补充备注（可选）" :disabled="savingSuggestionIds.has(item.id)" @blur="decideSuggestion(item)" @click.stop /></span></label></section></div>
            <div class="first-draft-requirements"><UiField v-model="firstDraftRequirements" label="本次成品补充要求" placeholder="例如：不要使用反问句，结尾不需要行动号召" multiline :rows="3" /></div>
          </section>
          <section v-else-if="tab === 'editing'" class="stage-content editing-stage">
            <div class="stage-heading"><div><h2>{{ selectedVersion?.label }}</h2></div><UiButton :icon="FileCheck2" :disabled="!selectedVersion || draftDirty" @click="finalize">设为定稿</UiButton></div>
            <TextEditor v-if="selectedVersion" v-model="editorText" :autosave-key="autosaveKey" :saving="operation === 'manual'" :locks="task.locks" :version-id="selectedVersion.id" @update:model-value="draftDirty = true" @save="saveManual" @lock="addLock" @toggle-sentence="toggleSentence" @revise-selection="startLocal" />
            <div class="revision-box"><UiField v-model="revisionInstruction" label="本轮修改要求" :placeholder="selectionRange ? '说明选中部分要怎么改' : '可选，例如：开头更直接，整体更口语化'" multiline :rows="3" /><div><span v-if="selectionRange" class="selection-scope">仅修改选中内容<button class="icon-button" aria-label="取消选区限制" title="取消选区限制" @click="selectionRange = null"><X :size="14" /></button></span><span v-else-if="allSentencesFixed" class="selection-scope">全部句子已保留</span><UiButton variant="primary" :icon="Sparkles" :loading="operation === 'revision'" :disabled="!editorText.trim() || allSentencesFixed" @click="run('revision')">{{ selectionRange ? '优化选区' : '再次生成' }}</UiButton></div></div>
          </section>
          <section v-else class="stage-content"><div class="stage-heading"><div><h2>当前定稿</h2><p>定稿仍然保留在版本历史中，后续可以继续创建子版本。</p></div><div v-if="finalVersion" class="export-actions"><UiButton size="small" :icon="Download" @click="exportFinal('txt')">TXT</UiButton><UiButton size="small" :icon="Download" @click="exportFinal('md')">Markdown</UiButton></div></div><div v-if="finalVersion" class="source-document final-document">{{ finalVersion.content }}</div><StatePanel v-else :icon="FileCheck2" title="还没有定稿" description="选择一个成品版本，确认后设为当前定稿。"><UiButton @click="tab = 'editing'">返回成品修改</UiButton></StatePanel></section>
        </main>
        </fieldset>
        <aside class="context-sidebar">
          <details open><summary>创作设置</summary><dl><div><dt>目标字数</dt><dd>{{ task.settings.targetCharacters }} 字</dd></div><div><dt>语言风格</dt><dd>{{ task.settings.languageStyle }}</dd></div><div><dt>目标受众</dt><dd>{{ task.settings.audience }}</dd></div></dl></details>
          <details v-if="task.locks.length" open><summary>逐字保留</summary><div class="lock-list"><div v-for="lock in task.locks" :key="lock.id"><LockKeyhole :size="15" /><span>{{ lock.text }}</span><button class="icon-button" type="button" title="取消保留" aria-label="取消保留" :disabled="aiBusy || !!operation" @click="removeLock(lock.id)"><Trash2 :size="14" /></button></div></div></details>
          <details v-if="task.versions.length" open><summary><History :size="16" />版本历史</summary><div class="version-list"><button v-for="version in [...task.versions].reverse()" :key="version.id" type="button" :class="{ active: selectedVersion?.id === version.id }" @click="selectVersion(version); tab = 'editing'"><span>{{ version.label }}</span><small>{{ new Date(version.createdAt).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) }}</small></button></div></details>
          <details v-if="task.versions.length > 1" class="desktop-editing"><summary><GitCompareArrows :size="16" />版本对比</summary><div class="version-compare"><select v-model="compareLeft" class="field-control" aria-label="对比原版本"><option v-for="version in task.versions" :key="version.id" :value="version.id">{{ version.label }}</option></select><select v-model="compareRight" class="field-control" aria-label="对比新版本"><option v-for="version in task.versions" :key="version.id" :value="version.id">{{ version.label }}</option></select><UiButton size="small" :icon="GitCompareArrows" :loading="comparing" :disabled="!compareLeft || !compareRight || compareLeft === compareRight" @click="compareVersions">查看差异</UiButton></div></details>
        </aside>
      </div>
      <div v-if="showDiff" class="modal-layer desktop-editing" role="presentation" @mousedown.self="showDiff = false"><section class="diff-dialog" role="dialog" aria-modal="true" aria-labelledby="diff-title"><header><div><h2 id="diff-title">版本差异</h2><p>减号为删除内容，加号为新增内容。</p></div><button class="icon-button" type="button" aria-label="关闭对比" @click="showDiff = false"><X :size="18" /></button></header><pre v-if="compareDiff" class="diff-output"><span v-for="(line, index) in compareDiff.split('\n')" :key="index" :class="{ added: line.startsWith('+') && !line.startsWith('+++'), removed: line.startsWith('-') && !line.startsWith('---'), meta: line.startsWith('@@') || line.startsWith('+++') || line.startsWith('---') }">{{ line }}{{ '\n' }}</span></pre><StatePanel v-else :icon="GitCompareArrows" title="两个版本没有文字差异" description="它们的正文内容完全一致。" /></section></div>
    </template>
  </div>
</template>
