<script setup lang="ts">
defineProps<{
  icon?: string
  title?: string
  description?: string
}>()
</script>

<template>
  <div class="empty-state">
    <div v-if="icon" class="empty-icon">{{ icon }}</div>
    <h3>{{ title || '暂无数据' }}</h3>
    <p v-if="description">{{ description }}</p>
  </div>
</template>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 64px 24px;
  text-align: center;
}
.empty-icon {
  font-size: 48px;
  margin-bottom: 16px;
  opacity: 0.6;
}
.empty-state h3 {
  font-size: 18px;
  font-weight: 600;
  color: var(--color-ink);
  margin: 0 0 8px;
}
.empty-state p {
  font-size: 14px;
  color: var(--color-mute);
  margin: 0;
}
</style>
