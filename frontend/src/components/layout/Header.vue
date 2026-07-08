<script setup lang="ts">
import { useRoute } from 'vue-router'
import { useUiStore } from '@/stores/ui'
import { computed } from 'vue'

const route = useRoute()
const ui = useUiStore()

const titles: Record<string, string> = {
  qa: '智能问答', agent: '智能分析', library: '论文库',
  summary: '摘要 & 综述', citations: '引用关系', data: '数据管理',
  system: '系统设置', help: '帮助',
}

const pageTitle = computed(() => titles[String(route.name)] || 'Paper Assistant')
</script>

<template>
  <header class="top-header">
    <div class="header-left">
      <button class="menu-toggle" @click="ui.toggleSidebar()" title="菜单">
        <span></span><span></span><span></span>
      </button>
      <h2 class="page-title">{{ pageTitle }}</h2>
    </div>
    <div class="header-right">
      <span class="api-status" title="API 状态">
        <span class="status-dot"></span>
        API
      </span>
    </div>
  </header>
</template>

<style scoped>
.top-header {
  display: flex; align-items: center; justify-content: space-between;
  height: 64px; padding: 0 24px;
  background: var(--color-canvas); border-bottom: 1px solid var(--color-hairline);
  position: sticky; top: 0; z-index: 30;
}
.header-left { display: flex; align-items: center; gap: 12px; }
.menu-toggle {
  display: none; flex-direction: column; gap: 4px;
  background: none; border: none; cursor: pointer;
  padding: 6px; border-radius: var(--radius-sm);
}
.menu-toggle:hover { background: var(--color-canvas-soft); }
.menu-toggle span {
  display: block; width: 20px; height: 2px;
  background: var(--color-ink); border-radius: 1px;
}
.page-title { font-size: 18px; font-weight: 600; color: var(--color-ink); letter-spacing: -0.36px; margin: 0; }
.api-status { display: flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 500; color: var(--color-mute); }
.status-dot { width: 6px; height: 6px; border-radius: 50%; background: #22c55e; }

@media (max-width: 768px) {
  .top-header { padding: 0 16px; }
  .menu-toggle { display: flex; }
}
</style>
