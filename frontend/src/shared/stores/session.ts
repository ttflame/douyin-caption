import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '../api/adapter'
import type { Member } from '../types'

export const useSessionStore = defineStore('session', () => {
  const token = ref(localStorage.getItem('dc_token') ?? '')
  const stored = localStorage.getItem('dc_member')
  const member = ref<Member | null>(stored ? JSON.parse(stored) as Member : null)
  const loading = ref(false)
  const error = ref('')
  const authenticated = computed(() => Boolean(token.value && member.value))
  async function login(username: string, password: string) {
    loading.value = true; error.value = ''
    try { const result = await api.login(username, password); token.value = result.token; member.value = result.member; localStorage.setItem('dc_token', result.token); localStorage.setItem('dc_member', JSON.stringify(result.member)) }
    catch (reason) { error.value = reason instanceof Error ? reason.message : '登录失败'; throw reason }
    finally { loading.value = false }
  }
  function logout() { token.value = ''; member.value = null; localStorage.removeItem('dc_token'); localStorage.removeItem('dc_member') }
  function expire() { logout(); error.value = '登录已过期，请重新登录后继续' }
  return { token, member, loading, error, authenticated, login, logout, expire }
})
