<script setup lang="ts">
import { ref, computed } from 'vue'
import { useUiStore } from '@/stores/ui'
import { useAuthStore } from '@/stores/auth'
import { useToastStore } from '@/stores/toast'

const ui = useUiStore()
const auth = useAuthStore()
const toast = useToastStore()

const username = ref('')
const password = ref('')
const confirm = ref('')
const error = ref('')
const successMsg = ref('')
const loading = ref(false)

const isLogin = computed(() => ui.authMode === 'login')

function close() {
  error.value = ''
  successMsg.value = ''
  username.value = ''
  password.value = ''
  confirm.value = ''
  ui.closeAuth()
}

function switchMode() {
  error.value = ''
  successMsg.value = ''
  username.value = ''
  password.value = ''
  confirm.value = ''
  ui.authMode = isLogin.value ? 'register' : 'login'
}

function validate(): boolean {
  if (!username.value.trim()) { error.value = '用户名不能为空'; return false }
  if (username.value.length < 3 || username.value.length > 20) { error.value = '用户名需 3-20 位'; return false }
  if (!/^[a-zA-Z0-9_]+$/.test(username.value)) { error.value = '只能包含英文字母、数字和下划线'; return false }
  if (!password.value) { error.value = '密码不能为空'; return false }
  if (password.value.length < 8) { error.value = '密码至少需要 8 个字符'; return false }
  if (!isLogin.value && password.value !== confirm.value) { error.value = '两次密码不一致'; return false }
  return true
}

async function submit() {
  error.value = ''
  successMsg.value = ''
  if (!validate()) return

  loading.value = true
  try {
    const endpoint = isLogin.value ? '/api/auth/login' : '/api/auth/register'
    const body: Record<string, string> = {
      username: username.value.trim(),
      password: password.value,
      mode: ui.authMode,
    }
    if (!isLogin.value) body.confirm = confirm.value

    const resp = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })

    const data = await resp.json().catch(() => ({}))
    if (!resp.ok) {
      error.value = (data as { detail?: string }).detail || `请求失败 (${resp.status})`
      return
    }

    if (!isLogin.value) {
      // Register success
      successMsg.value = '注册成功！请登录'
      toast.success('注册成功！请使用新账号登录')
      ui.authMode = 'login'
      password.value = ''
      confirm.value = ''
      return
    }

    // Login success
    const uname = (data as { username?: string }).username || username.value.trim()
    auth.login(uname)
    toast.success(`欢迎回来，${uname}`)
    close()
  } catch {
    error.value = '无法连接到服务器，请确认后端已启动'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="auth-overlay" @click.self="close">
    <div class="auth-card">
      <h3>{{ isLogin ? '登录' : '注册账号' }}</h3>
      <p class="auth-desc">欢迎使用 Paper Assistant — RAG 学术论文智能助手</p>

      <div class="form-group">
        <input
          v-model="username"
          class="form-input"
          type="text"
          placeholder="用户名（3-20位英文/数字/下划线）"
          autocomplete="username"
          @keyup.enter="submit"
        />
      </div>
      <div class="form-group">
        <input
          v-model="password"
          class="form-input"
          type="password"
          placeholder="密码（至少8位，需包含英文字母和数字）"
          autocomplete="current-password"
          @keyup.enter="submit"
        />
      </div>
      <div v-if="!isLogin" class="form-group">
        <input
          v-model="confirm"
          class="form-input"
          type="password"
          placeholder="再次输入密码"
          autocomplete="new-password"
          @keyup.enter="submit"
        />
      </div>

      <div v-if="error" class="auth-error">{{ error }}</div>
      <div v-if="successMsg" class="auth-success">{{ successMsg }}</div>

      <div class="auth-actions">
        <button class="btn-primary" style="width:100%" :disabled="loading" @click="submit">
          {{ loading ? '处理中…' : (isLogin ? '登录' : '注册') }}
        </button>
        <button class="btn-secondary" style="width:100%" @click="close">关闭</button>
      </div>

      <button class="switch-btn" @click="switchMode">
        {{ isLogin ? '还没有账号？注册账号' : '已有账号？返回登录' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.auth-overlay {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.4);
  display: flex; align-items: center; justify-content: center;
  z-index: 100; backdrop-filter: blur(4px);
}
.auth-card {
  background: var(--color-canvas);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-modal);
  padding: 32px; width: 400px; max-width: 90vw;
}
.auth-card h3 { margin: 0 0 4px; font-size: 20px; font-weight: 600; }
.auth-desc { font-size: 14px; color: var(--color-mute); margin: 0 0 20px; }
.form-group { margin-bottom: 12px; }
.auth-error { padding: 8px 12px; background: var(--color-error-soft); color: var(--color-error-deep); border-radius: var(--radius-sm); font-size: 13px; margin-bottom: 12px; }
.auth-success { padding: 8px 12px; background: #d1fae5; color: #059669; border-radius: var(--radius-sm); font-size: 13px; margin-bottom: 12px; }
.auth-actions { display: flex; flex-direction: column; gap: 8px; margin-top: 16px; }
.switch-btn { width: 100%; margin-top: 12px; background: none; border: none; font-size: 13px; color: var(--color-link); cursor: pointer; padding: 8px; }
.switch-btn:hover { text-decoration: underline; }
</style>
