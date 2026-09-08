import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '../api/adapter'
import type { CreativeSettings, RewriteTask } from '../types'

export const useTaskStore = defineStore('tasks', () => {
  const items = ref<RewriteTask[]>([])
  const current = ref<RewriteTask | null>(null)
  const loading = ref(false)
  const error = ref('')
  let loadGeneration = 0
  let requestedTaskId = ''
  const activeItems = computed(() => items.value.filter((item) => item.state !== 'archived'))
  async function load() { loading.value = true; error.value = ''; try { const [active, archived] = await Promise.all([api.listTasks(false), api.listTasks(true)]); items.value = [...active, ...archived.filter((item) => !active.some((activeItem) => activeItem.id === item.id))] } catch (reason) { error.value = reason instanceof Error ? reason.message : '任务加载失败' } finally { loading.value = false } }
  async function loadOne(taskId: string) {
    const generation = ++loadGeneration
    requestedTaskId = taskId; current.value = null; loading.value = true; error.value = ''
    try { const result = await api.getTask(taskId); if (generation === loadGeneration) current.value = result }
    catch (reason) { if (generation === loadGeneration) error.value = reason instanceof Error ? reason.message : '任务加载失败' }
    finally { if (generation === loadGeneration) loading.value = false }
  }
  async function refreshCurrent(taskId: string) {
    const generation = loadGeneration
    const result = await api.getTask(taskId)
    if (generation === loadGeneration && requestedTaskId === taskId) current.value = result
    items.value = items.value.map((item) => item.id === taskId ? result : item)
  }
  async function create(payload: { name: string; sourceText: string; settings: CreativeSettings }) { const task = await api.createTask(payload); items.value.unshift(task); return task }
  async function copy(taskId: string) { const task = await api.copyTask(taskId); items.value.unshift(task); return task }
  async function persist() { if (!current.value || current.value.state !== 'draft') return; current.value = await api.updateDraft(current.value) }
  async function archive(taskId: string) { await api.archiveTask(taskId); await load() }
  async function restore(taskId: string) { await api.restoreTask(taskId); await load() }
  return { items, current, loading, error, activeItems, load, loadOne, refreshCurrent, create, copy, persist, archive, restore }
})
