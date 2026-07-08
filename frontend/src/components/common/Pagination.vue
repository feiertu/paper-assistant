<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  page: number
  totalPages: number
  total: number
}>()

const emit = defineEmits<{
  change: [page: number]
}>()

const pages = computed(() => {
  const result: (number | string)[] = []
  const tp = props.totalPages
  const current = props.page

  if (tp <= 7) {
    for (let i = 1; i <= tp; i++) result.push(i)
    return result
  }

  result.push(1)
  if (current > 3) result.push('…')

  const start = Math.max(2, current - 1)
  const end = Math.min(tp - 1, current + 1)
  for (let i = start; i <= end; i++) result.push(i)

  if (current < tp - 2) result.push('…')
  result.push(tp)

  return result
})
</script>

<template>
  <div class="pagination">
    <span class="pagination-info">第 {{ page }}/{{ totalPages }} 页，共 {{ total }} 条</span>
    <div class="pagination-buttons">
      <button :disabled="page <= 1" @click="emit('change', page - 1)">‹</button>
      <template v-for="(p, i) in pages" :key="i">
        <span v-if="p === '…'" class="ellipsis">…</span>
        <button v-else :class="{ active: p === page }" @click="emit('change', p as number)">
          {{ p }}
        </button>
      </template>
      <button :disabled="page >= totalPages" @click="emit('change', page + 1)">›</button>
    </div>
  </div>
</template>

<style scoped>
.pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 0;
  flex-wrap: wrap;
  gap: 12px;
}
.pagination-info {
  font-size: 13px;
  color: var(--color-mute);
}
.pagination-buttons {
  display: flex;
  gap: 2px;
}
.pagination-buttons button {
  min-width: 32px;
  height: 32px;
  border: 1px solid var(--color-hairline);
  border-radius: var(--radius-sm);
  background: var(--color-canvas);
  color: var(--color-body);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.1s;
  display: flex;
  align-items: center;
  justify-content: center;
}
.pagination-buttons button:hover:not(:disabled) {
  border-color: var(--color-ink);
  color: var(--color-ink);
}
.pagination-buttons button.active {
  background: var(--color-primary);
  color: var(--color-on-primary);
  border-color: var(--color-primary);
}
.pagination-buttons button:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}
.ellipsis {
  display: flex;
  align-items: center;
  padding: 0 4px;
  color: var(--color-mute);
}
</style>
