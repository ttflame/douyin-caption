<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, BookmarkPlus, Save } from 'lucide-vue-next'
import UiButton from '../../shared/components/UiButton.vue'
import UiField from '../../shared/components/UiField.vue'
import CreativeSettingsFields from '../presets/CreativeSettingsFields.vue'
import { api, defaultSettings } from '../../shared/api/adapter'
import { useSessionStore } from '../../shared/stores/session'
import { useTaskStore } from '../../shared/stores/tasks'
import type { CreativePreset } from '../../shared/types'

const router = useRouter()
const route = useRoute()
const store = useTaskStore()
const session = useSessionStore()
const saving = ref(false)
const presetSaving = ref(false)
const loading = ref(false)
const error = ref('')
const presets = ref<CreativePreset[]>([])
const selectedPresetId = ref('')
const presetName = ref('')
const form = reactive({ name: '', sourceText: '', settings: { ...defaultSettings } })
const selectedPreset = computed(() => presets.value.find((item) => item.id === selectedPresetId.value))
const presetDirty = computed(() => Boolean(selectedPreset.value) && (presetName.value.trim() !== selectedPreset.value?.name || JSON.stringify(form.settings) !== JSON.stringify(selectedPreset.value?.settings)))
const editId = computed(() => typeof route.params.id === 'string' ? route.params.id : '')
const editing = computed(() => Boolean(editId.value))
const draftKey = computed(() => `${editing.value ? 'dc_task_edit' : 'dc_new_task'}:${session.member?.id ?? 'unknown'}:${editId.value || 'new'}`)
let autosaveTimer: number | undefined
watch(form, () => { window.clearTimeout(autosaveTimer); autosaveTimer = window.setTimeout(() => localStorage.setItem(draftKey.value, JSON.stringify(form)), 500) }, { deep: true })
function applyPreset() { const preset = selectedPreset.value; if (preset) { Object.assign(form.settings, preset.settings); presetName.value = preset.name } else { presetName.value = '' } }
async function savePreset() { if (!presetName.value.trim()) return; presetSaving.value = true; error.value = ''; try { const preset = selectedPresetId.value ? await api.updatePreset(selectedPresetId.value, presetName.value.trim(), { ...form.settings }) : await api.createPreset(presetName.value.trim(), { ...form.settings }); presets.value = [preset, ...presets.value.filter((item) => item.id !== preset.id)]; selectedPresetId.value = preset.id; presetName.value = preset.name } catch (reason) { error.value = reason instanceof Error ? reason.message : '预设保存失败' } finally { presetSaving.value = false } }
async function submit() {
  error.value = ''
  if (!form.name.trim() || !form.sourceText.trim()) { error.value = '请填写任务名称和原文'; return }
  if (form.sourceText.length > 20000) { error.value = '原文不能超过 20,000 字'; return }
  if (form.settings.targetCharacters < 1) { error.value = '目标字数必须是正整数'; return }
  saving.value = true
  try { const task = editing.value ? await api.updateDraft({ id: editId.value, name: form.name.trim(), sourceText: form.sourceText.trim(), settings: { ...form.settings }, state: 'draft', updatedAt: '', analysis: [], suggestions: [], versions: [], locks: [] }) : await store.create({ name: form.name.trim(), sourceText: form.sourceText.trim(), settings: { ...form.settings } }); window.clearTimeout(autosaveTimer); localStorage.removeItem(draftKey.value); await router.push(`/workbench/${task.id}`) }
  catch (reason) { error.value = reason instanceof Error ? reason.message : '任务创建失败' }
  finally { saving.value = false }
}
onMounted(async () => { loading.value = true; try { const [presetRows, task] = await Promise.all([api.listPresets(), editing.value ? api.getTask(editId.value) : Promise.resolve(null)]); presets.value = presetRows; if (task) Object.assign(form, { name: task.name, sourceText: task.sourceText, settings: { ...task.settings } }); const draft = localStorage.getItem(draftKey.value); if (draft) { try { const parsed = JSON.parse(draft) as typeof form; Object.assign(form, parsed); Object.assign(form.settings, parsed.settings) } catch { localStorage.removeItem(draftKey.value) } } } catch (reason) { error.value = reason instanceof Error ? reason.message : '页面加载失败' } finally { loading.value = false } })
onBeforeUnmount(() => window.clearTimeout(autosaveTimer))
</script>

<template>
  <div class="page narrow-page">
    <header class="page-header"><div><button class="text-back" type="button" @click="router.back()"><ArrowLeft :size="16" />返回任务</button><h1>{{ editing ? '编辑草稿任务' : '新建文案任务' }}</h1><p>{{ editing ? '仅草稿状态可以修改原文和创作设置。' : '这些设置会贯穿分析、建议和后续改写。' }}</p></div></header>
    <div v-if="loading" class="settings-skeleton"><span v-for="index in 5" :key="index" class="skeleton block" /></div>
    <form v-else class="creation-form" @submit.prevent="submit">
      <section class="preset-toolbar"><label><span class="preset-label">个人创作预设<small v-if="presetDirty">有未保存修改</small></span><select v-model="selectedPresetId" class="field-control" @change="applyPreset"><option value="">不使用预设</option><option v-for="preset in presets" :key="preset.id" :value="preset.id">{{ preset.name }}</option></select></label><label><span>预设名称</span><input v-model="presetName" class="field-control" maxlength="120" placeholder="输入预设名称" /></label><UiButton :icon="BookmarkPlus" :loading="presetSaving" :disabled="!presetName.trim() || (!!selectedPresetId && !presetDirty)" @click="savePreset">保存预设</UiButton></section>
      <section class="form-section"><div class="section-heading"><h2>原始文案</h2><span>{{ form.sourceText.length }} / 20,000 字</span></div><UiField v-model="form.name" label="任务名称" placeholder="便于以后查找，例如：新手做内容的三个误区" /><UiField v-model="form.sourceText" label="原文" placeholder="粘贴需要分析和改写的抖音口播稿" multiline :rows="10" /></section>
      <CreativeSettingsFields v-model="form.settings" />
      <div v-if="error" class="inline-alert error" role="alert">{{ error }}</div>
      <footer class="form-actions"><span>{{ editing ? '保存后返回任务工作台。' : '创建后进入结构分析，任务会自动保存。' }}</span><UiButton variant="primary" type="submit" :icon="Save" :loading="saving">{{ editing ? '保存修改' : '创建并继续' }}</UiButton></footer>
    </form>
  </div>
</template>
