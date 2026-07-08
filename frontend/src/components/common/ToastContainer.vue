<script setup lang="ts">
import { useToastStore } from '@/stores/toast'

const toast = useToastStore()
</script>

<template>
  <div class="toast-container">
    <TransitionGroup name="toast">
      <div
        v-for="t in toast.toasts"
        :key="t.id"
        :class="['toast', `toast-${t.type}`]"
        @click="toast.remove(t.id)"
      >
        <span class="toast-icon">
          {{ { success: '[OK]', error: '[X]', warning: '[!]', info: '[i]' }[t.type] }}
        </span>
        <span class="toast-msg">{{ t.message }}</span>
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.toast-container {
  position: fixed;
  top: 20px;
  right: 20px;
  z-index: 200;
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-width: 400px;
}
.toast {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-modal);
  font-size: 14px;
  cursor: pointer;
  transition: all 0.3s ease;
}
.toast-success { background: #d1fae5; color: #065f46; }
.toast-error   { background: #fee2e2; color: #991b1b; }
.toast-warning { background: #fef3c7; color: #92400e; }
.toast-info    { background: #dbeafe; color: #1e40af; }
.toast-icon { font-weight: 700; font-size: 16px; }
.toast-msg { flex: 1; }

.toast-enter-active { animation: slideIn 0.3s ease; }
.toast-leave-active { animation: slideOut 0.3s ease; }
@keyframes slideIn {
  from { transform: translateX(100%); opacity: 0; }
  to { transform: translateX(0); opacity: 1; }
}
@keyframes slideOut {
  from { transform: translateX(0); opacity: 1; }
  to { transform: translateX(100%); opacity: 0; }
}
</style>
