<script setup lang="ts">
import { useUiStore } from '@/stores/ui'
import Sidebar from './Sidebar.vue'
import Header from './Header.vue'
import AuthDialog from './AuthDialog.vue'
import ToastContainer from '@/components/common/ToastContainer.vue'
import ErrorBoundary from '@/components/common/ErrorBoundary.vue'
import { RouterView } from 'vue-router'

const ui = useUiStore()
</script>

<template>
  <div class="app-shell">
    <!-- Mobile overlay -->
    <div v-if="ui.sidebarOpen" class="sidebar-overlay" @click="ui.toggleSidebar()"></div>
    <Sidebar :class="{ open: ui.sidebarOpen }" />
    <div class="app-main">
      <Header />
      <main class="app-content">
        <ErrorBoundary>
          <RouterView />
        </ErrorBoundary>
      </main>
    </div>
    <AuthDialog v-if="ui.showAuthDialog" />
    <ToastContainer />
  </div>
</template>

<style scoped>
.app-shell { display: flex; min-height: 100vh; }
.app-main {
  flex: 1; margin-left: 260px;
  display: flex; flex-direction: column;
  transition: margin-left 0.3s ease;
}
.app-content {
  flex: 1; padding: 24px 32px;
  max-width: 1200px; width: 100%; box-sizing: border-box;
}
.sidebar-overlay {
  display: none; position: fixed; inset: 0;
  background: rgba(0,0,0,0.3); z-index: 35;
}

@media (max-width: 768px) {
  .app-main { margin-left: 0; }
  .app-content { padding: 16px; }
  .sidebar-overlay { display: block; }
}
</style>
