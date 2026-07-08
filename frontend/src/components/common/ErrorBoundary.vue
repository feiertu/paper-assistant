<script setup lang="ts">
import { ref, onErrorCaptured } from 'vue'

const error = ref<Error | null>(null)

onErrorCaptured((err) => {
  error.value = err as Error
  console.error('ErrorBoundary caught:', err)
  return false // prevent propagation
})

function reset() {
  error.value = null
}
</script>

<template>
  <div v-if="error" class="error-boundary">
    <div class="eb-card">
      <div class="eb-icon">!</div>
      <h3>页面出了点问题</h3>
      <p class="eb-detail">{{ error.message }}</p>
      <button class="btn-primary" @click="reset">重试</button>
    </div>
  </div>
  <slot v-else />
</template>

<style scoped>
.error-boundary {
  display: flex; align-items: center; justify-content: center;
  padding: 64px 24px;
}
.eb-card {
  text-align: center; padding: 48px;
  background: var(--color-canvas);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-modal);
  max-width: 480px;
}
.eb-icon {
  font-size: 24px; font-weight: 700;
  width: 48px; height: 48px;
  background: var(--color-warning-soft);
  color: var(--color-warning-deep);
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  margin: 0 auto 16px;
}
.eb-card h3 { margin: 0 0 8px; font-size: 18px; }
.eb-detail { font-size: 14px; color: var(--color-mute); margin: 0 0 20px; word-break: break-all; }
</style>
