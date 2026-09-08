<script setup lang="ts">
import { computed, ref } from 'vue'
import { useStorage } from '@vueuse/core'
import { useRoute, useRouter } from 'vue-router'
import { Archive, FilePenLine, LogOut, Menu, PanelLeftClose, PanelLeftOpen, Settings, SquarePen, Users, X } from 'lucide-vue-next'
import { useSessionStore } from '../stores/session'
import UiButton from '../components/UiButton.vue'
import WorkerCenter from '../components/WorkerCenter.vue'

const route = useRoute()
const router = useRouter()
const session = useSessionStore()
const mobileOpen = ref(false)
const collapsed = useStorage('dc_sidebar_collapsed', false)
const logoutDialog = ref<HTMLDialogElement | null>(null)
const isAdmin = computed(() => session.member?.role === 'admin')
const links = [
  { to: '/tasks', label: '文案任务', icon: FilePenLine },
  { to: '/tasks?view=archived', label: '已归档', icon: Archive },
  { to: '/settings', label: '系统设置', icon: Settings },
]
function active(to: string) {
  if (to.includes('?')) return route.fullPath === to
  if (to === '/tasks') return (route.path === '/tasks' && !route.query.view) || route.path.startsWith('/workbench')
  return route.path === to
}
function logout() { logoutDialog.value?.close(); session.logout(); router.replace('/login') }
</script>

<template>
  <div class="app-shell" :class="{ 'sidebar-collapsed': collapsed }">
    <header class="mobile-header">
      <button class="icon-button" type="button" aria-label="打开导航" @click="mobileOpen = true"><Menu :size="20" /></button>
      <span class="brand-mark"><SquarePen :size="18" /><span>口播工坊</span></span>
      <span class="mobile-spacer" />
    </header>
    <button v-if="mobileOpen" class="nav-scrim" type="button" aria-label="关闭导航" @click="mobileOpen = false" />
    <aside class="sidebar" :class="{ 'is-open': mobileOpen }">
      <div class="brand-row"><span class="brand-symbol" title="口播工坊"><SquarePen :size="17" /></span><span class="sidebar-label">口播工坊</span><button class="icon-button mobile-close" type="button" aria-label="关闭导航" @click="mobileOpen = false"><X :size="18" /></button></div>
      <nav class="main-nav" aria-label="主导航">
        <RouterLink v-for="link in links" :key="link.to" :to="link.to" :class="{ active: active(link.to) }" :aria-label="link.label" :title="collapsed ? link.label : undefined" @click="mobileOpen = false">
          <component :is="link.icon" :size="17" :stroke-width="1.7" /><span class="sidebar-label">{{ link.label }}</span>
        </RouterLink>
        <div v-if="isAdmin" class="admin-nav">
          <RouterLink to="/admin/members" :class="{ active: active('/admin/members') }" aria-label="成员管理" :title="collapsed ? '成员管理' : undefined" @click="mobileOpen = false"><Users :size="17" :stroke-width="1.7" /><span class="sidebar-label">成员管理</span></RouterLink>
        </div>
      </nav>
      <button class="icon-button sidebar-toggle" type="button" :aria-label="collapsed ? '展开侧边栏' : '收起侧边栏'" :title="collapsed ? '展开侧边栏' : '收起侧边栏'" :aria-expanded="!collapsed" @click="collapsed = !collapsed"><component :is="collapsed ? PanelLeftOpen : PanelLeftClose" :size="18" /></button>
      <div class="account-area">
        <div class="account-profile" :title="session.member?.displayName"><span class="avatar">{{ session.member?.displayName.slice(0, 1) }}</span><span class="sidebar-label"><span class="account-name">{{ session.member?.displayName }}</span><small>{{ isAdmin ? '管理员' : '内容成员' }}</small></span></div>
        <button class="nav-logout" type="button" aria-label="退出登录" :title="collapsed ? '退出登录' : undefined" @click="logoutDialog?.showModal()"><LogOut :size="16" /><span class="sidebar-label">退出登录</span></button>
      </div>
    </aside>
    <main class="app-main"><RouterView :key="route.path" /></main>
    <WorkerCenter v-show="!mobileOpen" />
    <dialog ref="logoutDialog" class="confirm-dialog" aria-labelledby="logout-title" aria-describedby="logout-description" @click.self="logoutDialog?.close()">
      <section class="confirm-dialog-body">
        <header><h2 id="logout-title">退出登录？</h2><button class="icon-button" type="button" aria-label="关闭确认窗口" @click="logoutDialog?.close()"><X :size="18" /></button></header>
        <p id="logout-description">退出后需要重新登录，未保存的修改可能丢失。</p>
        <footer><UiButton autofocus @click="logoutDialog?.close()">取消</UiButton><UiButton variant="primary" :icon="LogOut" @click="logout">确认退出</UiButton></footer>
      </section>
    </dialog>
  </div>
</template>
