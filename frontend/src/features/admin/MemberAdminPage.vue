<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Plus, Users } from 'lucide-vue-next'
import StatePanel from '../../shared/components/StatePanel.vue'
import ToggleSwitch from '../../shared/components/ToggleSwitch.vue'
import UiButton from '../../shared/components/UiButton.vue'
import UiField from '../../shared/components/UiField.vue'
import { api } from '../../shared/api/adapter'
import type { Member } from '../../shared/types'

const loading = ref(true); const error = ref(''); const members = ref<Member[]>([]); const showForm = ref(false); const saving = ref(false)
const form = reactive({ username: '', displayName: '', password: '' })
async function load() { loading.value = true; error.value = ''; try { members.value = await api.listMembers() } catch (reason) { error.value = reason instanceof Error ? reason.message : '成员列表加载失败' } finally { loading.value = false } }
async function toggle(member: Member) { const previous = member.active; member.active = !member.active; try { const updated = await api.updateMember(member); members.value = members.value.map((item) => item.id === updated.id ? updated : item) } catch (reason) { member.active = previous; error.value = reason instanceof Error ? reason.message : '状态更新失败' } }
async function create() { if (!form.username || !form.displayName || !form.password) return; saving.value = true; error.value = ''; try { const member = await api.createMember(form); members.value = [member, ...members.value]; Object.assign(form, { username: '', displayName: '', password: '' }); showForm.value = false } catch (reason) { error.value = reason instanceof Error ? reason.message : '成员创建失败' } finally { saving.value = false } }
onMounted(load)
</script>

<template>
  <div class="page"><header class="page-header"><div><h1>成员管理</h1><p>管理员只管理账号状态，无法查看成员文案。</p></div><UiButton variant="primary" :icon="Plus" @click="showForm = !showForm">创建成员</UiButton></header>
    <form v-if="showForm" class="inline-create" @submit.prevent="create"><UiField v-model="form.username" label="登录账号" /><UiField v-model="form.displayName" label="成员名称" /><UiField v-model="form.password" label="初始密码" type="password" /><UiButton variant="primary" type="submit" :loading="saving" :disabled="!form.username || !form.displayName || !form.password">确认创建</UiButton></form>
    <div v-if="error" class="inline-alert error">{{ error }}</div><div v-if="loading" class="data-list"><div v-for="index in 4" :key="index" class="data-row skeleton-row"><span class="skeleton block wide" /></div></div>
    <StatePanel v-else-if="members.length === 0" :icon="Users" title="还没有成员" description="创建首个成员账号后，对方即可登录自己的独立工作区。" />
    <div v-else class="data-list"><div class="data-head"><span>成员</span><span>角色</span><span>创建时间</span><span>状态</span></div><div v-for="member in members" :key="member.id" class="data-row"><span><span class="data-primary">{{ member.displayName }}</span><small>{{ member.username }}</small></span><span>{{ member.role === 'admin' ? '管理员' : '内容成员' }}</span><span>{{ new Date(member.createdAt).toLocaleDateString('zh-CN') }}</span><ToggleSwitch :model-value="member.active" :label="member.active ? '启用' : '停用'" @update:model-value="toggle(member)" /></div></div>
  </div>
</template>
