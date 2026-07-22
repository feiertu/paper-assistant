<script setup lang="ts">
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'
import { useToastStore } from '@/stores/toast'
import { useTheme } from '@/composables/useTheme'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const ui = useUiStore()
const toast = useToastStore()
const { theme, toggle: toggleTheme } = useTheme()

interface NavItem {
  key: string
  label: string
  icon: string
}

const navItems: NavItem[] = [
  { key: 'qa', label: '智能问答', icon: '' },
  { key: 'agent', label: '智能分析', icon: '' },
  { key: 'fetch', label: '论文抓取', icon: '' },
  { key: 'library', label: '论文库', icon: '' },
  { key: 'summary', label: '摘要 & 综述', icon: '' },
  { key: 'citations', label: '引用关系', icon: '' },
  { key: 'data', label: '数据管理', icon: '' },
  { key: 'system', label: '系统设置', icon: '' },
  { key: 'help', label: '帮助', icon: '' },
]

function navigate(key: string) {
  router.push(`/${key}`)
}

function isActive(key: string): boolean {
  return route.path === `/${key}`
}

function handleLogin() {
  ui.openAuth('login')
}

function handleLogout() {
  auth.logout()
  toast.info('已退出登录')
}
</script>

<template>
  <aside class="sidebar">
    <div class="sidebar-brand">
      <span class="brand-icon">PA</span>
      <div>
        <div class="brand-title">Paper Assistant</div>
        <div class="brand-subtitle">RAG 学术助手</div>
      </div>
    </div>

    <nav class="sidebar-nav">
      <button
        v-for="item in navItems"
        :key="item.key"
        :class="['nav-item', { active: isActive(item.key) }]"
        @click="navigate(item.key)"
      >
        <span v-if="item.icon" class="nav-icon">{{ item.icon }}</span>
        <span class="nav-label">{{ item.label }}</span>
      </button>
    </nav>

    <div class="sidebar-footer">
      <!-- Theme toggle -->
      <button class="theme-toggle" @click="toggleTheme()" :title="theme === 'light' ? '切换暗色模式' : '切换亮色模式'">
        {{ theme === 'light' ? 'Dark' : 'Light' }}
      </button>

      <div v-if="auth.isLoggedIn" class="user-info">
        <span class="user-avatar">{{ auth.user?.[0]?.toUpperCase() }}</span>
        <span class="user-name">{{ auth.user }}</span>
        <button class="logout-btn" @click="handleLogout" title="退出登录">→</button>
      </div>
      <button v-else class="login-btn" @click="handleLogin">
        登录 / 注册
      </button>
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  position: fixed;
  top: 0;
  left: 0;
  bottom: 0;
  width: 260px;
  background: var(--color-canvas-soft);
  border-right: 1px solid var(--color-hairline);
  display: flex;
  flex-direction: column;
  z-index: 40;
  overflow-y: auto;
}

.sidebar-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 20px 24px;
  border-bottom: 1px solid var(--color-hairline);
}
.brand-icon {
  font-size: 16px;
  font-weight: 700;
  background: var(--color-primary);
  color: var(--color-on-primary);
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-md);
  letter-spacing: -0.5px;
}
.brand-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--color-ink);
  letter-spacing: -0.32px;
}
.brand-subtitle {
  font-size: 12px;
  color: var(--color-mute);
  margin-top: 2px;
}

.sidebar-nav {
  flex: 1;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 10px 12px;
  background: transparent;
  border: none;
  border-radius: var(--radius-sm);
  font-size: 14px;
  font-weight: 500;
  color: var(--color-body);
  cursor: pointer;
  transition: all 0.1s ease;
  text-align: left;
}
.nav-item:hover {
  background: var(--color-canvas-soft-2);
  color: var(--color-ink);
}
.nav-item.active {
  background: var(--color-canvas);
  color: var(--color-ink);
  box-shadow: var(--shadow-card);
}
.nav-icon {
  font-size: 16px;
  width: 20px;
  text-align: center;
}

.sidebar-footer {
  padding: 16px 24px;
  border-top: 1px solid var(--color-hairline);
}
.theme-toggle {
  width: 100%; padding: 6px; margin-bottom: 8px;
  background: var(--color-canvas); border: 1px solid var(--color-hairline);
  border-radius: var(--radius-sm); font-size: 14px; cursor: pointer;
  transition: all 0.15s;
}
.theme-toggle:hover { background: var(--color-canvas-soft-2); }
.user-info {
  display: flex;
  align-items: center;
  gap: 10px;
}
.user-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: var(--color-primary);
  color: var(--color-on-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 600;
}
.user-name {
  flex: 1;
  font-size: 14px;
  font-weight: 500;
  color: var(--color-ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.logout-btn {
  background: none;
  border: 1px solid var(--color-hairline);
  border-radius: var(--radius-sm);
  width: 28px;
  height: 28px;
  cursor: pointer;
  color: var(--color-mute);
  font-size: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
}
.logout-btn:hover {
  color: var(--color-ink);
  border-color: var(--color-hairline-strong);
}
.login-btn {
  width: 100%;
  padding: 8px 16px;
  background: var(--color-canvas);
  border: 1px solid var(--color-hairline);
  border-radius: var(--radius-sm);
  font-size: 14px;
  font-weight: 500;
  color: var(--color-ink);
  cursor: pointer;
  transition: all 0.15s;
}
.login-btn:hover {
  background: var(--color-canvas-soft-2);
}

@media (max-width: 768px) {
  .sidebar {
    transform: translateX(-100%);
    transition: transform 0.3s ease;
  }
  .sidebar.open {
    transform: translateX(0);
  }
}
</style>
