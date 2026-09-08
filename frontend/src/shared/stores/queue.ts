import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '../api/adapter'
import type { AiOperation } from '../types'

export const operationLabels = { analysis: '结构分析', suggestions: '优化方案', first_draft: '生成第一版', revision: '文案修改' }
export const isActiveOperation = (item: AiOperation) => item.status === 'queued' || item.status === 'running'

export const useQueueStore = defineStore('queue', () => {
  const items = ref<AiOperation[]>([])
  const expanded = ref(false)
  const error = ref('')
  const notice = ref<AiOperation | null>(null)
  const updates = ref<Record<string, AiOperation>>({})
  const active = computed(() => items.value.filter(isActiveOperation))
  const actionId = ref('')
  let owner = ''
  let generation = 0
  let revision = 0
  let timer: ReturnType<typeof setTimeout> | undefined

  function accept(item: AiOperation) {
    const previous = items.value.find((row) => row.id === item.id)
    if (previous && isActiveOperation(previous) && !isActiveOperation(item)) {
      updates.value[item.taskId] = item
      notice.value = item
    }
    items.value = [item, ...items.value.filter((row) => row.id !== item.id)]
    revision++
  }

  async function refresh() {
    const run = generation
    const version = revision
    try {
      const rows = await api.listOperations()
      if (run !== generation || version !== revision) return
      for (const row of rows) {
        const previous = items.value.find((item) => item.id === row.id)
        if (previous && isActiveOperation(previous) && !isActiveOperation(row)) {
          updates.value[row.taskId] = row
          notice.value = row
        }
      }
      items.value = rows
      error.value = ''
    } catch (reason) {
      if (run === generation) error.value = reason instanceof Error ? reason.message : '任务状态暂时无法同步'
    }
  }

  async function poll(run: number) {
    await refresh()
    if (run === generation && owner) timer = setTimeout(() => void poll(run), active.value.length ? 1500 : 5000)
  }

  function stop() {
    generation++; revision++; owner = ''; clearTimeout(timer)
    items.value = []; updates.value = {}; notice.value = null; error.value = ''; expanded.value = false; actionId.value = ''
  }

  function start(memberId: string) {
    if (owner === memberId) return
    stop(); owner = memberId
    if (owner) void poll(generation)
  }

  async function submit(request: () => Promise<AiOperation>) {
    const run = generation
    const result = await request()
    if (run === generation) { accept(result); expanded.value = true; error.value = '' }
    return result
  }

  async function control(item: AiOperation, action: 'cancel' | 'retry') {
    if (actionId.value) return
    const run = generation
    actionId.value = item.id
    try {
      const result = await (action === 'cancel' ? api.cancelOperation(item.id) : api.retryOperation(item.id))
      if (run === generation) { accept(result); error.value = '' }
    } catch (reason) {
      if (run === generation) error.value = reason instanceof Error ? reason.message : '操作失败，请重试'
    } finally { if (run === generation) actionId.value = '' }
  }

  return { items, expanded, error, notice, updates, active, actionId, start, stop, refresh, submit, control }
})
