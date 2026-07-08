<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  status: string
}>()

const badgeClass = computed(() => {
  const map: Record<string, string> = {
    ingested: 'badge badge-success',
    pending: 'badge badge-warning',
    failed: 'badge badge-error',
  }
  return map[props.status] || 'badge badge-muted'
})

const label = computed(() => {
  const map: Record<string, string> = {
    ingested: '已入库',
    pending: '待处理',
    failed: '失败',
  }
  return map[props.status] || props.status
})
</script>

<template>
  <span :class="badgeClass">{{ label }}</span>
</template>
