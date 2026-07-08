<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useToastStore } from '@/stores/toast'
import { storeApi, queriesApi, papersApi } from '@/api/client'
import type { StoreStats, Paper, QueryRecord } from '@/api/types'

const auth = useAuthStore()
const toast = useToastStore()
const tab = ref<'ingest' | 'export' | 'history'>('ingest')
const storeStats = ref<StoreStats>({ count: 0 })
const ingestPapers = ref<Paper[]>([])
const queries = ref<QueryRecord[]>([])
const loading = ref(false)

// Export
const expFmt = ref<'json' | 'csv'>('json')
const expLimit = ref(100)
const expType = ref<'papers' | 'queries'>('papers')

onMounted(async () => {
  try {
    const [stats, p, q] = await Promise.all([
      storeApi.stats(auth.ownerId),
      storeApi.papers(auth.ownerId),
      queriesApi.list(auth.ownerId, 30),
    ])
    storeStats.value = stats
    ingestPapers.value = p
    queries.value = Array.isArray(q) ? q : q.queries || []
  } catch { /* */ }
})

async function doIngest() {
  loading.value = true
  try {
    const result = await storeApi.ingest(auth.ownerId)
    toast.success(`入库完成: ${result.papers} 篇论文, ${result.chunks} 个分块`)
    location.reload()
  }
  catch (e) {
    const msg = e instanceof Error ? e.message : '未知错误'
    toast.error('入库失败: ' + msg)
    console.error('Ingest error:', e)
  }
  finally { loading.value = false }
}

async function doClearQueries() {
  try { await queriesApi.clear(auth.ownerId); queries.value = []; }
  catch (e) { console.error(e) }
}

function exportUrl(): string {
  if (expType.value === 'papers') {
    return `/api/export/papers?fmt=${expFmt.value}&limit=${expLimit.value}`
  }
  return `/api/export/queries?fmt=${expFmt.value}&limit=${expLimit.value}`
}
</script>

<template>
  <div class="data-page">
    <h2>数据管理</h2>
    <div class="tabs">
      <button :class="{ active: tab === 'ingest' }" @click="tab = 'ingest'">入库</button>
      <button :class="{ active: tab === 'export' }" @click="tab = 'export'">导出</button>
      <button :class="{ active: tab === 'history' }" @click="tab = 'history'">历史</button>
    </div>

    <!-- Ingest -->
    <div v-if="tab === 'ingest'" class="tab-content">
      <div class="metric-card"><span class="metric-value">{{ storeStats.count }}</span><span class="metric-label">向量库 chunks</span></div>
      <button class="btn-primary mt-4" :disabled="loading" @click="doIngest">{{ loading ? '入库中…' : '执行入库' }}</button>
      <div v-if="ingestPapers.length" class="mt-4">
        <details><summary>已入库论文（{{ ingestPapers.length }} 篇）</summary>
          <div v-for="p in ingestPapers" :key="p.arxiv_id" class="paper-item">
            {{ p.arxiv_id }}: {{ (p.title || '').slice(0, 80) }}
          </div>
        </details>
      </div>
    </div>

    <!-- Export -->
    <div v-if="tab === 'export'" class="tab-content">
      <div class="form-section">
        <select v-model="expFmt" class="form-input" style="width:auto"><option value="json">JSON</option><option value="csv">CSV</option></select>
        <input v-model.number="expLimit" class="form-input" type="number" min="10" max="500" style="width:80px" />
        <select v-model="expType" class="form-input" style="width:auto"><option value="papers">论文</option><option value="queries">查询历史</option></select>
        <a :href="exportUrl()" target="_blank" class="btn-primary" style="text-decoration:none">导出</a>
      </div>
    </div>

    <!-- History -->
    <div v-if="tab === 'history'" class="tab-content">
      <button v-if="queries.length" class="btn-secondary mb-4" @click="doClearQueries">清空历史</button>
      <div v-if="!queries.length" class="empty">暂无查询记录</div>
      <div v-for="q in queries" :key="q.id" class="paper-card" style="margin-bottom:8px">
        <div class="query-text">{{ (q.query_text || '').slice(0, 60) }}…</div>
        <div class="query-meta">{{ q.created_at }} | 语言: {{ q.lang }} | 命中: {{ q.hit_count }}</div>
        <div v-if="q.answer_text" class="query-answer">{{ (q.answer_text || '').slice(0, 300) }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.data-page { max-width: 900px; }
.tabs { display: flex; gap: 0; margin-bottom: 24px; border-bottom: 1px solid var(--color-hairline); }
.tabs button {
  padding: 10px 20px; background: none; border: none; font-size: 14px; font-weight: 500;
  color: var(--color-mute); cursor: pointer; border-bottom: 2px solid transparent;
}
.tabs button:hover { color: var(--color-ink); }
.tabs button.active { color: var(--color-ink); border-bottom-color: var(--color-ink); }
.tab-content { padding: 8px 0; }
.metric-card { display: inline-flex; flex-direction: column; align-items: center; padding: 16px 24px; background: var(--color-canvas); border-radius: var(--radius-md); box-shadow: var(--shadow-card); margin-right: 16px; }
.metric-value { font-size: 28px; font-weight: 600; color: var(--color-ink); }
.metric-label { font-size: 12px; color: var(--color-mute); }
.mt-4 { margin-top: 16px; }
.mb-4 { margin-bottom: 16px; }
.form-section { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.paper-item { font-size: 12px; color: var(--color-mute); padding: 4px 0; }
.query-text { font-size: 14px; font-weight: 600; color: var(--color-ink); }
.query-meta { font-size: 12px; color: var(--color-mute); margin-top: 4px; }
.query-answer { font-size: 13px; color: var(--color-body); margin-top: 4px; }
.empty { color: var(--color-mute); padding: 24px 0; }
</style>
