<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { Check, KeyRound, LockKeyhole, PlugZap, Save, Trash2 } from 'lucide-vue-next'
import UiButton from '../../shared/components/UiButton.vue'
import UiField from '../../shared/components/UiField.vue'
import { api } from '../../shared/api/adapter'

const loading = ref(true)
const saving = ref(false)
const testing = ref(false)
const passwordSaving = ref(false)
const providerDeleting = ref(false)
const confirmDelete = ref(false)
const message = ref('')
const error = ref('')
const form = reactive({ configured: false, maskedKey: '', apiKey: '', baseUrl: '', modelId: '', timeoutSeconds: 240 })
const savedConnection = reactive({ baseUrl: '', modelId: '' })
const timeoutError = computed(() => Number.isInteger(form.timeoutSeconds) && form.timeoutSeconds >= 10 && form.timeoutSeconds <= 600 ? '' : '请输入 10–600 之间的整数秒数')
const canSaveTimeoutOnly = computed(() => form.configured && form.baseUrl === savedConnection.baseUrl && form.modelId === savedConnection.modelId)
const canSave = computed(() => !timeoutError.value && form.baseUrl && form.modelId && (form.apiKey.trim() || canSaveTimeoutOnly.value))
const passwordForm = reactive({ current: '', next: '', confirmation: '' })
function rememberConnection() { Object.assign(savedConnection, { baseUrl: form.baseUrl, modelId: form.modelId }) }
onMounted(async () => { try { Object.assign(form, await api.getProvider()); rememberConnection() } catch (reason) { error.value = reason instanceof Error ? reason.message : '设置加载失败，请刷新重试' } finally { loading.value = false } })
async function save() {
  if (!canSave.value || saving.value) return
  saving.value = true; message.value = ''; error.value = ''
  try {
    const result = form.apiKey.trim() ? await api.saveProvider(form) : await api.saveProviderTimeout(form.timeoutSeconds)
    Object.assign(form, result, { apiKey: '' }); rememberConnection(); message.value = '设置已保存'
  } catch (reason) { error.value = reason instanceof Error ? reason.message : '保存失败，请稍后重试' }
  finally { saving.value = false }
}
async function test() { testing.value = true; message.value = ''; error.value = ''; try { const result = await api.testProvider(form); if (!result.success) throw new Error(typeof result.message === 'string' ? result.message : '连接失败'); message.value = typeof result.message === 'string' ? result.message : '连接正常，可以开始调用模型' } catch (reason) { error.value = reason instanceof Error ? reason.message : '连接失败，请检查请求地址和密钥' } finally { testing.value = false } }
async function changePassword() { message.value = ''; error.value = ''; if (passwordForm.next.length < 8) { error.value = '新密码至少需要 8 个字符'; return } if (passwordForm.next !== passwordForm.confirmation) { error.value = '两次输入的新密码不一致'; return } passwordSaving.value = true; try { await api.changePassword(passwordForm.current, passwordForm.next); Object.assign(passwordForm, { current: '', next: '', confirmation: '' }); message.value = '密码已修改' } catch (reason) { error.value = reason instanceof Error ? reason.message : '密码修改失败' } finally { passwordSaving.value = false } }
async function deleteProvider() { if (!confirmDelete.value) { confirmDelete.value = true; return } providerDeleting.value = true; message.value = ''; error.value = ''; try { await api.deleteProvider(); Object.assign(form, { configured: false, maskedKey: '', apiKey: '', baseUrl: 'https://api.openai.com/v1', modelId: '', timeoutSeconds: 240 }); rememberConnection(); confirmDelete.value = false; message.value = '模型连接已删除' } catch (reason) { error.value = reason instanceof Error ? reason.message : '连接删除失败' } finally { providerDeleting.value = false } }
</script>

<template>
  <div class="page narrow-page">
    <header class="page-header"><div><h1>系统设置</h1><p>模型请求由服务器发出，密钥不会在保存后回显。</p></div></header>
    <div v-if="loading" class="settings-skeleton"><span v-for="index in 5" :key="index" class="skeleton block" /></div>
    <div v-else class="settings-stack">
      <section class="form-section"><div class="section-heading"><div><h2>OpenAI 连接</h2><p>每位成员使用自己的请求地址和密钥。</p></div><span v-if="form.configured" class="connection-state"><Check :size="15" />已配置</span></div>
        <div v-if="form.maskedKey" class="saved-key"><KeyRound :size="18" /><span><small>当前密钥</small>{{ form.maskedKey }}</span></div>
        <UiField v-model="form.apiKey" label="API Key" type="password" placeholder="修改密钥、地址或模型时需要输入" />
        <UiField v-model="form.baseUrl" label="请求地址" type="url" placeholder="https://api.openai.com/v1" />
        <UiField v-model="form.modelId" label="默认模型" placeholder="请输入模型名称" />
        <UiField v-model="form.timeoutSeconds" label="服务器响应时长限制（秒）" type="number" :min="10" :max="600" :error="timeoutError" />
        <div v-if="form.configured" class="danger-action"><div><span>删除模型连接</span><small>删除后需要重新配置才能生成文案。</small></div><UiButton variant="danger" :icon="Trash2" :loading="providerDeleting" @click="deleteProvider">{{ confirmDelete ? '确认删除' : '删除连接' }}</UiButton></div>
      </section>
      <section class="form-section"><div class="section-heading"><div><h2>登录密码</h2><p>修改后使用新密码再次登录。</p></div><LockKeyhole :size="19" /></div><UiField v-model="passwordForm.current" label="当前密码" type="password" /><div class="two-columns"><UiField v-model="passwordForm.next" label="新密码" type="password" hint="至少 8 个字符" /><UiField v-model="passwordForm.confirmation" label="确认新密码" type="password" /></div><div class="section-action"><UiButton :icon="Save" :loading="passwordSaving" :disabled="!passwordForm.current || !passwordForm.next || !passwordForm.confirmation" @click="changePassword">修改密码</UiButton></div></section>
      <div v-if="message" class="inline-alert success" role="status">{{ message }}</div><div v-if="error" class="inline-alert error" role="alert">{{ error }}</div>
      <footer class="form-actions"><UiButton :icon="PlugZap" :loading="testing" :disabled="!form.baseUrl || !form.modelId || !!timeoutError" @click="test">测试连接</UiButton><UiButton variant="primary" :icon="Save" :loading="saving" :disabled="!canSave" @click="save">保存设置</UiButton></footer>
    </div>
  </div>
</template>
