<script setup lang="ts">
defineProps<{
  text?: string
}>()
</script>

<template>
  <div class="thinking-indicator">
    <div class="thinking-dots">
      <span class="dot"></span>
      <span class="dot"></span>
      <span class="dot"></span>
    </div>
    <span class="thinking-text">{{ text || '分析中…' }}</span>
  </div>
</template>

<style scoped>
.thinking-indicator {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  background: var(--color-canvas);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-card);
}
.thinking-text {
  font-size: 13px;
  color: var(--color-mute);
}
</style>
