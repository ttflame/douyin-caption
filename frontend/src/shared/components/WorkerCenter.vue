<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { ArrowUpRight, Check, ChevronDown, CircleAlert, Clock3, ListTodo, LoaderCircle, RotateCcw, Trash2, X } from 'lucide-vue-next'
import { useSessionStore } from '../stores/session'
import { operationLabels, useQueueStore } from '../stores/queue'
import type { AiOperation } from '../types'
import UiButton from './UiButton.vue'

const session = useSessionStore()
const queue = useQueueStore()
const now = ref(Date.now())
const clock = setInterval(() => { now.value = Date.now() }, 1000)
watch(() => session.member?.id, (id) => { if (id) queue.start(id); else queue.stop() }, { immediate: true })
onUnmounted(() => { clearInterval(clock); queue.stop() })
const rows = computed(() => [...queue.items].sort((a, b) => {
  const rank = { running: 0, queued: 1, failed: 2, succeeded: 2, cancelled: 2 }
  return rank[a.status] - rank[b.status] || (a.status === 'queued' ? a.createdAt.localeCompare(b.createdAt) : b.createdAt.localeCompare(a.createdAt))
}))
const running = computed(() => queue.active.find((row) => row.status === 'running'))
const queuedCount = computed(() => queue.active.filter((row) => row.status === 'queued').length)
const historyCount = computed(() => queue.items.length - queue.active.length)
const clearDialog = ref<HTMLDialogElement | null>(null)
const statuses = { queued: '排队中', running: '执行中', succeeded: '已完成', failed: '失败', cancelled: '已取消' }
function elapsed(item: AiOperation) {
  if (!item.startedAt) return ''
  const timestamp = (value: string) => Date.parse(/[zZ]|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`)
  const seconds = Math.max(0, Math.floor(((item.completedAt ? timestamp(item.completedAt) : now.value) - timestamp(item.startedAt)) / 1000))
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}
async function clearHistory() { clearDialog.value?.close(); await queue.clearHistory() }
</script>

<template>
  <aside class="worker-center" aria-label="后台任务中心">
    <div v-if="queue.notice && !queue.expanded" class="worker-notice" role="status">
      <RouterLink :to="`/workbench/${queue.notice.taskId}`" @click="queue.notice = null">{{ queue.notice.taskName }} · {{ statuses[queue.notice.status] }}</RouterLink>
      <button class="icon-button" aria-label="关闭任务通知" title="关闭通知" @click="queue.notice = null"><X :size="16" /></button>
    </div>
    <section v-if="queue.expanded" id="worker-panel" class="worker-panel" aria-label="任务队列">
      <header><span>任务中心</span><button class="icon-button clear-history" aria-label="清除任务历史" title="清除任务历史" :disabled="!historyCount || !!queue.actionId" @click="clearDialog?.showModal()"><Trash2 :size="16" /></button><span class="worker-count">{{ queue.active.length }} 项待完成</span><button class="icon-button" aria-label="收起任务中心" title="收起" @click="queue.expanded = false"><ChevronDown :size="18" /></button></header>
      <p v-if="queue.error" class="worker-error" role="alert">{{ queue.error }}</p>
      <div class="worker-list">
        <p v-if="!rows.length" class="worker-empty">暂无任务</p>
        <article v-for="item in rows" :key="item.id" class="worker-row">
          <component :is="item.status === 'running' ? LoaderCircle : item.status === 'queued' ? Clock3 : item.status === 'failed' ? CircleAlert : item.status === 'succeeded' ? Check : X" :size="17" :class="{ 'worker-spinner': item.status === 'running' }" />
          <div class="worker-detail"><RouterLink :to="`/workbench/${item.taskId}`" :title="item.taskName">{{ item.taskName }}</RouterLink><small>{{ operationLabels[item.kind] }} · {{ statuses[item.status] }} <time v-if="item.startedAt">{{ elapsed(item) }}</time></small><p v-if="item.error">{{ item.error.message }}</p></div>
          <div class="worker-tools">
            <button v-if="item.status === 'queued'" class="icon-button" :disabled="!!queue.actionId" :aria-label="`取消排队：${item.taskName}`" title="取消排队" @click="queue.control(item, 'cancel')"><X :size="16" /></button>
            <button v-if="item.status === 'failed' || item.status === 'cancelled'" class="icon-button" :disabled="!!queue.actionId || queue.active.some(row => row.taskId === item.taskId)" :aria-label="`重试：${item.taskName}`" title="重试" @click="queue.control(item, 'retry')"><RotateCcw :size="16" /></button>
            <RouterLink class="icon-button" :to="`/workbench/${item.taskId}`" :aria-label="`查看文案：${item.taskName}`" title="查看文案"><ArrowUpRight :size="16" /></RouterLink>
          </div>
        </article>
      </div>
    </section>
    <dialog ref="clearDialog" class="confirm-dialog" aria-labelledby="clear-history-title" @click.self="clearDialog?.close()"><section class="confirm-dialog-body"><header><h2 id="clear-history-title">清除任务历史？</h2><button class="icon-button" type="button" aria-label="关闭确认窗口" @click="clearDialog?.close()"><X :size="18" /></button></header><p>将清除已完成、失败和已取消的记录。排队中和执行中的任务会保留；失败任务清除后不能从这里重试。</p><footer><UiButton @click="clearDialog?.close()">取消</UiButton><UiButton variant="danger" :icon="Trash2" @click="clearHistory">确认清除</UiButton></footer></section></dialog>
    <button class="worker-toggle" :aria-expanded="queue.expanded" aria-controls="worker-panel" aria-label="任务中心" @click="queue.expanded = !queue.expanded; queue.notice = null">
      <component :is="running ? LoaderCircle : ListTodo" :size="19" :class="{ 'worker-spinner': running }" /><span>{{ running ? `${operationLabels[running.kind]} ${elapsed(running)}` : '任务中心' }}</span><span v-if="queuedCount" class="worker-badge">{{ queuedCount }} 排队</span><CircleAlert v-if="queue.error" :size="16" />
    </button>
  </aside>
</template>

<style scoped>
.worker-center { position: fixed; right: 24px; bottom: 20px; z-index: 35; display: flex; flex-direction: column; align-items: flex-end; gap: 10px; max-width: calc(100% - 32px); }
.worker-toggle { display: flex; align-items: center; gap: 10px; min-height: 46px; padding: 0 16px; border: 0; border-radius: 8px; background: #28574b; color: #fff; box-shadow: 0 4px 18px #193e3026; cursor: pointer; transition: background .18s; }
.worker-toggle:hover { background: #356b5d; }
.worker-badge { font-size: 12px; color: #d7e8e0; }
.worker-panel { width: 370px; max-width: 100%; border-radius: 8px; background: #fff; box-shadow: 0 8px 36px #253c3426; overflow: hidden; }
.worker-panel header { display: flex; align-items: center; gap: 10px; padding: 10px 14px; background: #edf2f0; font-size: 14px; }
.clear-history { width: 28px; height: 28px; color: #6a7871; }
.worker-count { margin-left: auto; font-size: 12px; color: #66756e; }
.worker-list { max-height: min(430px, 55dvh); overflow-y: auto; scrollbar-gutter: stable; }
.worker-list::-webkit-scrollbar { width: 5px; }
.worker-list::-webkit-scrollbar-thumb { border-radius: 4px; background: transparent; }
.worker-list:hover::-webkit-scrollbar-thumb { background: #c9d3ce; }
.worker-row { display: flex; align-items: flex-start; gap: 10px; padding: 14px 12px; transition: background .18s; }
.worker-row:hover { background: #f6f8f7; }
.worker-row > svg { flex-shrink: 0; margin-top: 3px; color: #627a70; }
.worker-detail { flex: 1; min-width: 0; }
.worker-detail > a { display: block; color: #273d33; text-decoration: none; font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.worker-detail > a:hover { text-decoration: underline; }
.worker-detail small { display: block; margin-top: 5px; color: #6a7871; font-size: 12px; }
.worker-detail time { margin-left: 5px; font-variant-numeric: tabular-nums; }
.worker-detail p, .worker-error { font-size: 12px; color: #80534c; line-height: 1.6; overflow-wrap: anywhere; margin: 6px 0 0; }
.worker-error { padding: 10px 14px; }
.worker-tools { display: flex; flex-shrink: 0; }
.worker-tools .icon-button { width: 28px; height: 28px; color: #627a70; text-decoration: none; }
.worker-empty { text-align: center; color: #7b8781; padding: 30px 0; font-size: 13px; }
.worker-notice { display: flex; align-items: center; gap: 8px; max-width: 370px; padding: 10px 12px; border-radius: 8px; background: #fff; box-shadow: 0 4px 18px #193e3026; font-size: 13px; }
.worker-notice a { color: #28574b; overflow-wrap: anywhere; }
.worker-spinner { animation: worker-spin 1.6s linear infinite; }
@keyframes worker-spin { to { transform: rotate(360deg); } }
@media (max-width: 600px) {
  .worker-center { right: 16px; bottom: max(12px, env(safe-area-inset-bottom)); }
  .worker-panel { width: min(358px, calc(100vw - 32px)); }
  .worker-toggle { width: 46px; padding: 0; justify-content: center; }
  .worker-toggle > span { display: none; }
}
@media (prefers-reduced-motion: reduce) { .worker-spinner { animation: none; } }
</style>
