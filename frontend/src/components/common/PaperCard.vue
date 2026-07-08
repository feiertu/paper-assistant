<script setup lang="ts">
import type { Paper } from '@/api/types'
import StatusBadge from './StatusBadge.vue'

defineProps<{
  paper: Paper
  showAbstract?: boolean
}>()

defineEmits<{
  click: [arxivId: string]
}>()
</script>

<template>
  <div class="paper-card" @click="$emit('click', paper.arxiv_id)">
    <div class="paper-title">{{ paper.title || paper.arxiv_id }}</div>
    <div class="paper-authors">{{ paper.authors || '未知作者' }}</div>
    <div class="paper-meta">
      <span>{{ paper.published || '未知' }}</span>
      <span>{{ paper.arxiv_id }}</span>
      <span>{{ paper.chunk_count }} chunks</span>
      <StatusBadge :status="paper.ingest_status" />
    </div>
    <div v-if="showAbstract && paper.abstract" class="paper-abstract">
      {{ paper.abstract.slice(0, 400) }}{{ paper.abstract.length > 400 ? '…' : '' }}
    </div>
  </div>
</template>

<style scoped>
.paper-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--color-ink);
  margin-bottom: 4px;
  line-height: 1.4;
}
.paper-authors {
  font-size: 13px;
  color: var(--color-body);
  margin-bottom: 8px;
}
.paper-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 12px;
  color: var(--color-mute);
}
.paper-abstract {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--color-hairline);
  font-size: 13px;
  line-height: 1.6;
  color: var(--color-body);
}
</style>
