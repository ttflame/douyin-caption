import { createRouter, createWebHistory } from 'vue-router'
import { useSessionStore } from '../shared/stores/session'
import AppShell from '../shared/layouts/AppShell.vue'
import LoginPage from '../features/auth/LoginPage.vue'
import TaskListPage from '../features/tasks/TaskListPage.vue'
import NewTaskPage from '../features/tasks/NewTaskPage.vue'
import SettingsPage from '../features/settings/SettingsPage.vue'
import MemberAdminPage from '../features/admin/MemberAdminPage.vue'
import WorkbenchPage from '../features/workbench/WorkbenchPage.vue'
import PresetManagementPage from '../features/presets/PresetManagementPage.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: LoginPage, meta: { public: true } },
    { path: '/', component: AppShell, children: [
      { path: '', redirect: '/tasks' },
      { path: 'tasks', component: TaskListPage },
      { path: 'tasks/new', component: NewTaskPage },
      { path: 'tasks/:id/edit', component: NewTaskPage },
      { path: 'presets', component: PresetManagementPage },
      { path: 'workbench/:id', component: WorkbenchPage },
      { path: 'settings', component: SettingsPage },
      { path: 'admin/members', component: MemberAdminPage, meta: { admin: true } },
    ] },
    { path: '/:pathMatch(.*)*', redirect: '/tasks' },
  ],
})

router.beforeEach((to) => {
  const session = useSessionStore()
  if (!to.meta.public && !session.authenticated) return '/login'
  if (to.path === '/login' && session.authenticated) return '/tasks'
  if (to.meta.admin && session.member?.role !== 'admin') return '/tasks'
})

window.addEventListener('dc:unauthorized', () => { void router.replace('/login') })
