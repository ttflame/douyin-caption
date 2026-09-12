<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { BookmarkPlus, Save, Trash2, X } from 'lucide-vue-next'
import { api, defaultSettings } from '../../shared/api/adapter'
import UiButton from '../../shared/components/UiButton.vue'
import type { CreativePreset, CreativeSettings } from '../../shared/types'
import CreativeSettingsFields from './CreativeSettingsFields.vue'

const presets = ref<CreativePreset[]>([])
const selectedId = ref('')
const name = ref('')
const settings = ref<CreativeSettings>({ ...defaultSettings })
const loading = ref(true)
const saving = ref(false)
const deleting = ref(false)
const error = ref('')
const deleteDialog = ref<HTMLDialogElement | null>(null)
const selected = computed(() => presets.value.find((item) => item.id === selectedId.value))
const dirty = computed(() => !selected.value || name.value.trim() !== selected.value.name || JSON.stringify(settings.value) !== JSON.stringify(selected.value.settings))

function choose(preset: CreativePreset) {
  selectedId.value = preset.id
  name.value = preset.name
  settings.value = { ...preset.settings }
  error.value = ''
}

function createNew() {
  selectedId.value = ''
  name.value = ''
  settings.value = { ...defaultSettings }
  error.value = ''
}

async function save() {
  if (!name.value.trim() || settings.value.targetCharacters < 1) return
  saving.value = true
  error.value = ''
  try {
    const saved = selectedId.value
      ? await api.updatePreset(selectedId.value, name.value.trim(), { ...settings.value })
      : await api.createPreset(name.value.trim(), { ...settings.value })
    presets.value = [saved, ...presets.value.filter((item) => item.id !== saved.id)]
    choose(saved)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '预设保存失败'
  } finally {
    saving.value = false
  }
}

async function remove() {
  if (!selectedId.value) return
  deleteDialog.value?.close()
  deleting.value = true
  error.value = ''
  try {
    await api.deletePreset(selectedId.value)
    presets.value = presets.value.filter((item) => item.id !== selectedId.value)
    if (presets.value[0]) choose(presets.value[0]); else createNew()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '预设删除失败'
  } finally {
    deleting.value = false
  }
}

onMounted(async () => {
  try {
    presets.value = await api.listPresets()
    if (presets.value[0]) choose(presets.value[0])
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '预设加载失败'
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="page preset-page">
    <header class="page-header"><div><h1>预设方案管理</h1><p>保存常用的目标字数、人物受众、表达方式和输出约束。</p></div><UiButton :icon="BookmarkPlus" @click="createNew">新建预设</UiButton></header>
    <div v-if="loading" class="settings-skeleton"><span v-for="index in 5" :key="index" class="skeleton block" /></div>
    <div v-else class="preset-workspace">
      <aside class="preset-library" aria-label="预设列表">
        <p v-if="!presets.length" class="preset-empty">还没有保存的预设</p>
        <button v-for="preset in presets" :key="preset.id" type="button" :class="{ active: selectedId === preset.id }" @click="choose(preset)">
          <span>{{ preset.name }}</span><small>{{ preset.settings.targetLengthMode === 'follow_source' ? '跟随原文' : `${preset.settings.targetCharacters} 字` }}</small>
        </button>
      </aside>
      <main class="preset-editor">
        <section class="preset-name-row"><label><span>预设名称</span><input v-model="name" class="field-control" maxlength="120" placeholder="例如：职场观点口播" /></label><div><UiButton v-if="selectedId" variant="danger" :icon="Trash2" :loading="deleting" @click="deleteDialog?.showModal()">删除</UiButton><UiButton variant="primary" :icon="Save" :loading="saving" :disabled="!name.trim() || !dirty" @click="save">保存预设</UiButton></div></section>
        <CreativeSettingsFields v-model="settings" />
        <div v-if="error" class="inline-alert error" role="alert">{{ error }}</div>
      </main>
    </div>
    <dialog ref="deleteDialog" class="confirm-dialog" aria-labelledby="delete-preset-title" @click.self="deleteDialog?.close()"><section class="confirm-dialog-body"><header><h2 id="delete-preset-title">删除这个预设？</h2><button class="icon-button" type="button" aria-label="关闭确认窗口" @click="deleteDialog?.close()"><X :size="18" /></button></header><p>删除后无法恢复，不会影响已经创建的文案任务。</p><footer><UiButton @click="deleteDialog?.close()">取消</UiButton><UiButton variant="danger" :icon="Trash2" @click="remove">确认删除</UiButton></footer></section></dialog>
  </div>
</template>
