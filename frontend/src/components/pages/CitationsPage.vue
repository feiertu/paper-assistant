<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useToastStore } from '@/stores/toast'
import { storeApi, papersApi, citationsApi } from '@/api/client'
import type { CitationGraph, CitationStats } from '@/api/types'
import EmptyState from '@/components/common/EmptyState.vue'
import CitationGraphViz from '@/components/common/CitationGraph.vue'
import ThinkingIndicator from '@/components/common/ThinkingIndicator.vue'

const auth = useAuthStore()
const toast = useToastStore()
const papers = ref<{ arxiv_id: string; title: string }[]>([])
const selected = ref('')
const graph = ref<CitationGraph>({ cites: [], cited_by: [] })
const stats = ref<CitationStats>({ total: 0 })
const loading = ref(false)

onMounted(async () => {
  try { papers.value = await storeApi.papers(auth.ownerId) } catch { /* */ }
})

async function loadGraph() {
  if (!selected.value) return
  loading.value = true
  try {
    const [g, s] = await Promise.all([
      papersApi.citations(auth.ownerId, selected.value),
      citationsApi.stats(auth.ownerId),
    ])
    graph.value = g
    stats.value = s
  } catch (e) {
    toast.error('加载引用关系失败')
  }
  finally { loading.value = false }
}

async function extractAll() {
  try {
    const r = await citationsApi.extract(auth.ownerId)
    toast.success(`提取完成`)
    if (selected.value) await loadGraph()
  } catch (e) {
    toast.error('提取引用失败')
  }
}

function selectedLabel(): string {
  const p = papers.value.find(p => p.arxiv_id === selected.value)
  return p ? (p.title || p.arxiv_id).slice(0, 40) : selected.value
}
</script>

<template>
  <div class="citations-page">
    <h2>引用关系</h2>
    <p class="page-desc">查看论文之间的引用网络，提取和分析引用图谱。</p>

    <EmptyState v-if="!papers.length" title="暂无论文" description="请先导入论文数据" />

    <div v-else>
      <div class="form-section">
        <select v-model="selected" class="form-input" @change="loadGraph">
          <option value="">选择论文…</option>
          <option v-for="p in papers" :key="p.arxiv_id" :value="p.arxiv_id">
            {{ p.arxiv_id }} — {{ (p.title || '').slice(0, 60) }}
          </option>
        </select>
        <button class="btn-secondary" @click="extractAll">提取全部引用</button>
      </div>

      <div v-if="selected">
        <!-- Metrics -->
        <div class="metrics">
          <div class="metric"><span class="metric-value">{{ graph.cites.length }}</span><span class="metric-label">引用了</span></div>
          <div class="metric"><span class="metric-value">{{ graph.cited_by.length }}</span><span class="metric-label">被引用</span></div>
          <div class="metric"><span class="metric-value">{{ stats.total }}</span><span class="metric-label">全库引用</span></div>
        </div>

        <!-- Graph visualization -->
        <CitationGraphViz
          :cites="graph.cites"
          :cited-by="graph.cited_by"
          :center-label="selectedLabel()"
        />

        <ThinkingIndicator v-if="loading" text="加载中…" />

        <!-- Detail lists -->
        <div class="citation-tabs">
          <div class="citation-section">
            <h3>引用了 ({{ graph.cites.length }})</h3>
            <div v-if="!graph.cites.length" class="empty">未找到引用记录</div>
            <div v-for="c in graph.cites" :key="c.cited_arxiv_id" class="paper-card" style="margin-bottom:8px">
              <div class="cite-title">{{ c.cited_title || c.cited_arxiv_id }}</div>
              <div class="cite-meta">{{ c.cited_arxiv_id }} <span class="badge" :class="c.in_db ? 'badge-info' : 'badge-muted'">{{ c.in_db ? '在库' : '外部' }}</span></div>
            </div>
          </div>
          <div class="citation-section">
            <h3>被引用 ({{ graph.cited_by.length }})</h3>
            <div v-if="!graph.cited_by.length" class="empty">暂无其他论文引用此篇</div>
            <div v-for="c in graph.cited_by" :key="c.citing_arxiv_id" class="paper-card" style="margin-bottom:8px">
              <div class="cite-title">{{ c.citing_title || c.citing_arxiv_id }}</div>
              <div class="cite-meta">{{ c.citing_arxiv_id }} <span class="badge" :class="c.in_db ? 'badge-info' : 'badge-muted'">{{ c.in_db ? '在库' : '外部' }}</span></div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.citations-page { max-width: 1000px; }
.page-desc { font-size: 14px; color: var(--color-body); margin-bottom: 20px; }
.form-section { display: flex; gap: 12px; align-items: center; margin-bottom: 20px; }
.metrics { display: flex; gap: 24px; margin-bottom: 20px; }
.metric { display: flex; flex-direction: column; align-items: center; padding: 16px 24px; background: var(--color-canvas); border-radius: var(--radius-md); box-shadow: var(--shadow-card); min-width: 80px; }
.metric-value { font-size: 28px; font-weight: 600; color: var(--color-ink); }
.metric-label { font-size: 12px; color: var(--color-mute); margin-top: 4px; }
.citation-tabs { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin-top: 20px; }
.citation-section h3 { font-size: 16px; margin-bottom: 12px; }
.cite-title { font-size: 15px; font-weight: 600; color: var(--color-ink); margin-bottom: 4px; }
.cite-meta { font-size: 12px; color: var(--color-mute); display: flex; gap: 8px; align-items: center; }
.empty { color: var(--color-mute); font-size: 14px; padding: 16px 0; }
@media (max-width: 768px) { .citation-tabs { grid-template-columns: 1fr; } }
</style>
