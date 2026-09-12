<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowRight, FileText, SquarePen } from 'lucide-vue-next'
import UiButton from '../../shared/components/UiButton.vue'
import UiField from '../../shared/components/UiField.vue'
import { useSessionStore } from '../../shared/stores/session'
import { consumeReturnTo } from './returnTo'

const username = ref(import.meta.env.VITE_DEFAULT_LOGIN_USERNAME ?? '')
const password = ref(import.meta.env.VITE_DEFAULT_LOGIN_PASSWORD ?? '')
const session = useSessionStore()
const router = useRouter()
const route = useRoute()
async function submit() { try { await session.login(username.value, password.value); await router.replace(consumeReturnTo()) } catch { /* Store renders the safe error. */ } }
</script>

<template>
  <main class="login-page">
    <section class="login-intro">
      <div class="brand-lockup"><span class="brand-symbol large"><SquarePen :size="20" /></span><span>口播工坊</span></div>
      <div><h1>把一篇口播稿，改到真正能说出口。</h1><p>从结构判断到逐句定稿，完整保留每一次选择和修改。</p></div>
      <div class="intro-note"><FileText :size="19" /><span>成员内容彼此独立，管理员无法查看文案正文。</span></div>
    </section>
    <section class="login-form-wrap">
      <form class="login-form" @submit.prevent="submit">
        <div><h2>登录工作台</h2><p>{{ route.query.expired === '1' ? '登录已过期，请重新登录后继续' : '使用管理员为你创建的成员账号。' }}</p></div>
        <div v-if="session.error" class="inline-alert error" role="alert">{{ session.error }}</div>
        <UiField v-model="username" label="账号" autocomplete="username" />
        <UiField v-model="password" label="密码" type="password" />
        <UiButton variant="primary" type="submit" :loading="session.loading" :disabled="!username || !password" :icon="ArrowRight">进入工作台</UiButton>
        <p class="login-help">账号由管理员创建，无法登录时请联系管理员检查账号状态。</p>
      </form>
    </section>
  </main>
</template>
