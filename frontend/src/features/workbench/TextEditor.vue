<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { Clipboard, LockKeyhole, Pencil, Redo2, Save, Sparkles, Undo2 } from 'lucide-vue-next'
import UiButton from '../../shared/components/UiButton.vue'
import type { TextLock } from '../../shared/types'
import { codePointOffset, sentenceSelections, type SentenceSelection } from './sentences'

const props = withDefaults(defineProps<{ modelValue: string; autosaveKey: string; saving?: boolean; locks?: TextLock[]; versionId?: string }>(), { locks: () => [] })
const emit = defineEmits<{ 'update:modelValue': [value: string]; save: []; lock: [payload: { text: string; start: number; end: number }]; toggleSentence: [payload: SentenceSelection]; reviseSelection: [payload: { text: string; start: number; end: number }] }>()
const mode = ref<'sentences' | 'edit'>('sentences')
const textarea = ref<HTMLTextAreaElement | null>(null)
const localValue = ref(props.modelValue)
const history = ref<string[]>([props.modelValue])
const historyIndex = ref(0)
const selection = ref({ text: '', start: 0, end: 0, x: 0, y: 0 })
const copied = ref(false)
let autosaveTimer: number | undefined
const count = computed(() => localValue.value.length)
const sentences = computed(() => sentenceSelections(localValue.value, props.locks, props.versionId))
watch([() => props.modelValue, () => props.autosaveKey], ([value, key], previous) => {
  if (value === localValue.value && previous?.[1] === key) return
  window.clearTimeout(autosaveTimer)
  const draft = localStorage.getItem(key)
  localValue.value = draft ?? value
  history.value = [value]
  historyIndex.value = 0
  if (draft !== null && draft !== value) emit('update:modelValue', draft)
}, { immediate: true })
function input(event: Event) { const value = (event.target as HTMLTextAreaElement).value; const key = props.autosaveKey; localValue.value = value; emit('update:modelValue', value); window.clearTimeout(autosaveTimer); autosaveTimer = window.setTimeout(() => localStorage.setItem(key, value), 500) }
function commitHistory() { if (history.value[historyIndex.value] === localValue.value) return; history.value = history.value.slice(0, historyIndex.value + 1); history.value.push(localValue.value); historyIndex.value += 1 }
function restore(index: number) { const value = history.value[index]; if (value === undefined) return; historyIndex.value = index; localValue.value = value; emit('update:modelValue', value) }
function updateSelection(event: MouseEvent | KeyboardEvent) {
  const target = textarea.value
  if (!target) return
  const start = target.selectionStart
  const end = target.selectionEnd
  const text = target.value.slice(start, end)
  const x = event instanceof MouseEvent ? event.clientX : target.getBoundingClientRect().left + 24
  const y = event instanceof MouseEvent ? event.clientY : target.getBoundingClientRect().top + 74
  selection.value = text.trim() ? { text, start, end, x: Math.min(x, window.innerWidth - 250), y: Math.max(72, y - 54) } : { text: '', start: 0, end: 0, x: 0, y: 0 }
}
function selectedRange() { return { text: selection.value.text, start: codePointOffset(localValue.value, selection.value.start), end: codePointOffset(localValue.value, selection.value.end) } }
function lock() { emit('lock', selectedRange()); selection.value.text = ''; textarea.value?.focus() }
function revise() { emit('reviseSelection', selectedRange()); selection.value.text = '' }
async function copy() { await navigator.clipboard.writeText(localValue.value); copied.value = true; window.setTimeout(() => copied.value = false, 1200) }
async function focusEditor() { await nextTick(); textarea.value?.focus() }
defineExpose({ focusEditor })
onBeforeUnmount(() => window.clearTimeout(autosaveTimer))
watch(mode, () => { selection.value.text = '' })
</script>

<template>
  <div class="editor-shell">
    <div class="sentence-toolbar">
      <div class="editor-modes" role="group" aria-label="成品操作模式">
        <button type="button" :aria-pressed="mode === 'sentences'" @click="mode = 'sentences'"><LockKeyhole :size="15" />按句锁定</button>
        <button type="button" :aria-pressed="mode === 'edit'" @click="mode = 'edit'"><Pencil :size="15" />编辑</button>
      </div>
      <span>{{ count }} 字<span v-if="locks.length"> · 已保留 {{ locks.length }} 处</span></span>
      <button class="icon-button" type="button" title="复制全文" aria-label="复制全文" @click="copy"><Clipboard :size="17" /></button>
    </div>
    <div v-if="mode === 'edit'" class="editor-toolbar">
      <div><button class="icon-button" type="button" title="撤销" aria-label="撤销" :disabled="historyIndex === 0" @click="restore(historyIndex - 1)"><Undo2 :size="17" /></button><button class="icon-button" type="button" title="重做" aria-label="重做" :disabled="historyIndex >= history.length - 1" @click="restore(historyIndex + 1)"><Redo2 :size="17" /></button><button class="icon-button" type="button" title="复制全文" aria-label="复制全文" @click="copy"><Clipboard :size="17" /></button></div>
      <span>{{ copied ? '已复制' : `${count} 字` }}</span>
      <UiButton size="small" :icon="Save" :loading="saving" @click="emit('save')">保存为新版本</UiButton>
    </div>
    <div v-if="mode === 'sentences'" class="sentence-document" aria-label="按句锁定文案"><template v-for="(sentence, index) in sentences" :key="index">{{ sentence.leading }}<button v-if="sentence.text" class="sentence-button" type="button" :aria-pressed="sentence.lockIds.length > 0" :aria-label="`${sentence.lockIds.length ? '取消保留' : '锁定句子'}：${sentence.text}`" :title="sentence.lockIds.length ? '取消保留' : '锁定此句'" @click="emit('toggleSentence', sentence)"><span v-for="(part, partIndex) in sentence.parts" :key="partIndex" :class="{ 'locked-sentence': part.locked }">{{ part.text }}</span></button>{{ sentence.trailing }}</template></div>
    <textarea v-else ref="textarea" class="script-editor" :value="localValue" spellcheck="false" aria-label="成品文案编辑器" @input="input" @blur="commitHistory" @mouseup="updateSelection" @keyup="updateSelection" />
    <div v-if="selection.text" class="selection-popover" :style="{ left: `${selection.x}px`, top: `${selection.y}px` }">
      <button type="button" @mousedown.prevent="lock"><LockKeyhole :size="15" />设为保留</button>
      <button type="button" @mousedown.prevent="revise"><Sparkles :size="15" />局部修改</button>
    </div>
  </div>
</template>

<style scoped>
.sentence-toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; padding: 10px 12px; min-height: 54px; border-bottom: 1px solid #e3e8e5; }
.sentence-toolbar > span { margin-left: auto; color: var(--text-soft); font-size: 12px; }
.editor-modes { display: flex; gap: 3px; padding: 3px; background: #eef1ef; border-radius: 6px; }
.editor-modes button { display: flex; align-items: center; gap: 5px; min-height: 32px; border: 0; padding: 0 10px; border-radius: 4px; background: transparent; font-size: 13px; cursor: pointer; transition: background .18s, color .18s; }
.editor-modes button[aria-pressed="true"] { background: #fff; color: var(--accent-dark); box-shadow: 0 1px 4px #293d3014; }
.sentence-document { min-height: 300px; max-height: min(60dvh, 620px); overflow-y: auto; scrollbar-gutter: stable; padding: 24px 26px; white-space: pre-wrap; line-height: 2.2; overflow-wrap: anywhere; }
.sentence-button { display: inline; border: 0; padding: 2px 0; border-radius: 4px; background: transparent; color: inherit; font-weight: 400; text-align: left; line-height: inherit; white-space: pre-wrap; overflow-wrap: anywhere; cursor: pointer; transition: background .18s; }
.sentence-button:hover { background: #edf2ef; }
.locked-sentence { background: #d6eddf; color: #175f39; border-radius: 3px; box-decoration-break: clone; -webkit-box-decoration-break: clone; }
.sentence-document::-webkit-scrollbar { width: 5px; }
.sentence-document::-webkit-scrollbar-thumb { border-radius: 4px; background: transparent; }
.sentence-document:hover::-webkit-scrollbar-thumb { background: #c5d0c9; }
@media (max-width: 600px) { .sentence-document { padding: 18px 16px; } .sentence-toolbar > span { font-size: 11px; } }
</style>
