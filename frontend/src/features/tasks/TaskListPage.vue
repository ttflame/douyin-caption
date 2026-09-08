<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Archive, ArchiveRestore, Copy, FilePlus2, FileText, RefreshCw, Search } from 'lucide-vue-next'
import StatePanel from '../../shared/components/StatePanel.vue'
import UiButton from '../../shared/components/UiButton.vue'
import { useTaskStore } from '../../shared/stores/tasks'
import { useQueueStore } from '../../shared/stores/queue'
import type { TaskState } from '../../shared/types'

const store = useTaskStore()
const queue = useQueueStore()
const taskOperation = (id: string) => queue.active.find(item => item.taskId === id)
const route = useRoute()
const router = useRouter()
const search = ref('')
const filter = ref<'all' | TaskState>('all')
const copyingId = ref('')
const archived = computed(() => route.query.view === 'archived')
const stateLabel: Record<TaskState, string> = { draft: '待分析', analyzing: '分析中', analysis_ready: '分析完成', suggesting: '生成建议中', suggestions_ready: '待选方案', generating: '生成中', editing: '修改中', revising: '修改中', finalized: '已定稿', archived: '已归档' }
const tasks = computed(() => store.items.filter((task) => (archived.value ? task.state === 'archived' : task.state !== 'archived')).filter((task) => filter.value === 'all' || task.state === filter.value).filter((task) => task.name.toLowerCase().includes(search.value.toLowerCase())))
const title = computed(() => archived.value ? '已归档任务' : '文案任务')
function date(value: string) { return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(value)) }
async function copyTask(taskId: string) { copyingId.value = taskId; try { const copied = await store.copy(taskId); await router.push(`/tasks/${copied.id}/edit`) } catch (reason) { store.error = reason instanceof Error ? reason.message : '任务复制失败' } finally { copyingId.value = '' } }
onMounted(store.load)
watch(() => queue.updates, () => void store.load(), { deep: true })
watch(() => route.query.view, () => { search.value = ''; filter.value = 'all' })
</script>

<template>
  <div class="page task-page">
    <header class="page-header"><div><h1>{{ title }}</h1><p>{{ archived ? '查看并恢复暂时收起的任务。' : '每个任务对应一篇独立成品，历史过程会一直保留。' }}</p></div><UiButton v-if="!archived" variant="primary" :icon="FilePlus2" @click="router.push('/tasks/new')">新建任务</UiButton></header>
    <div class="list-toolbar">
      <label class="search-box"><Search :size="17" /><span class="sr-only">搜索任务</span><input v-model="search" placeholder="搜索任务名称" /></label>
      <select v-model="filter" class="compact-select" aria-label="按状态筛选"><option value="all">全部状态</option><option value="draft">待分析</option><option value="analysis_ready">分析完成</option><option value="suggestions_ready">待选方案</option><option value="editing">修改中</option><option value="finalized">已定稿</option></select>
    </div>
    <div v-if="store.error" class="inline-alert error" role="alert"><span>{{ store.error }}</span><UiButton size="small" :icon="RefreshCw" @click="store.load">重试</UiButton></div>
    <div v-else-if="store.loading" class="task-list" aria-label="正在加载任务"><div v-for="index in 4" :key="index" class="task-row skeleton-row"><span class="skeleton block wide" /><span class="skeleton block narrow" /></div></div>
    <StatePanel v-else-if="tasks.length === 0" :icon="FileText" :title="search || filter !== 'all' ? '没有匹配的任务' : archived ? '还没有归档任务' : '开始第一篇口播稿'" :description="search || filter !== 'all' ? '调整搜索词或筛选条件后再试。' : archived ? '归档后的任务会显示在这里。' : '先设置目标字数、表达风格和内容约束，再进入结构分析。'">
      <UiButton v-if="!archived && !search && filter === 'all'" variant="primary" :icon="FilePlus2" @click="router.push('/tasks/new')">新建任务</UiButton>
    </StatePanel>
    <div v-else class="task-list">
      <article v-for="task in tasks" :key="task.id" class="task-row" tabindex="0" @keydown.enter="router.push(`/workbench/${task.id}`)">
        <button class="task-main" type="button" @click="router.push(`/workbench/${task.id}`)"><span class="task-name">{{ task.name }}</span><span class="task-meta">{{ task.settings.targetCharacters ? `${task.settings.targetCharacters} 字 · ` : '' }}更新于 {{ date(task.updatedAt) }}</span></button>
        <span class="status-chip" :data-state="task.state">{{ taskOperation(task.id)?.status === 'queued' ? '排队中' : taskOperation(task.id)?.status === 'running' ? '执行中' : stateLabel[task.state] }}</span>
        <div class="task-actions"><button class="icon-button" type="button" title="复制为新任务" aria-label="复制为新任务" :disabled="copyingId === task.id" @click="copyTask(task.id)"><Copy :size="17" /></button><button v-if="task.state === 'archived'" class="icon-button" type="button" title="恢复任务" aria-label="恢复任务" @click="store.restore(task.id)"><ArchiveRestore :size="17" /></button><button v-else class="icon-button" type="button" title="归档任务" aria-label="归档任务" :disabled="!!taskOperation(task.id)" @click="store.archive(task.id)"><Archive :size="17" /></button></div>
      </article>
    </div>
  </div>
</template>
