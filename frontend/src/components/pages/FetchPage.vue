<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useToastStore } from '@/stores/toast'
import { arxivApi, fetchApi } from '@/api/client'
import type { FetchRecord } from '@/api/types'
import Pagination from '@/components/common/Pagination.vue'
import EmptyState from '@/components/common/EmptyState.vue'

const auth = useAuthStore()
const toast = useToastStore()

// ── Fetch form state ──
const fetchQuery = ref('cat:cs.AI AND ti:learning')
const fetchN = ref(5)
const fetching = ref(false)

// ── Last result state ──
interface LastResult {
  total_found: number
  fetched: number
  skipped: number
  failed: number
  skipped_papers: { id: string; title: string }[]
}
const lastResult = ref<LastResult | null>(null)
const showSkipped = ref(true)

// ── History state ──
const history = ref<FetchRecord[]>([])
const historyTotal = ref(0)
const historyPage = ref(1)
const historyLimit = ref(20)
const historyLoading = ref(false)
const expandedId = ref<number | null>(null)
const expandedDetail = ref<FetchRecord | null>(null)
const detailLoading = ref(false)

// ── Derived ──
const historyTotalPages = computed(() => Math.max(1, Math.ceil(historyTotal.value / historyLimit.value)))

// ── Fetch pipeline ──
async function doFetch() {
  fetching.value = true
  lastResult.value = null
  try {
    const result = await arxivApi.pipeline(auth.ownerId, fetchQuery.value, fetchN.value)

    // Show step-by-step toasts
    for (const step of result.steps) {
      const labels: Record<string, string> = { fetch: '搜索', download: '下载', parse: '解析', ingest: '入库' }
      const label = labels[step.step] || step.step
      if (step.step === 'fetch') toast.info(`${label}: 找到 ${step.count} 篇`)
      else if (step.step === 'download') toast.info(`${label}: 成功 ${step.success} 篇${step.failed ? `, 失败 ${step.failed} 篇` : ''}`)
      else if (step.step === 'ingest') toast.success(`${label}: ${step.papers} 篇 / ${step.chunks} chunks`)
    }

    // Get latest history record for result display
    const hResp = await fetchApi.history(auth.ownerId, 1, 0)
    if (hResp.records.length > 0) {
      const latest = hResp.records[0]
      lastResult.value = {
        total_found: latest.total_found,
        fetched: latest.fetched,
        skipped: latest.skipped,
        failed: latest.download_failed + latest.parse_failed,
        skipped_papers: latest.skipped_papers,
      }
    }
    await loadHistory()
    toast.success('管道完成！')
  } catch (e) {
    toast.error('arXiv 抓取失败：' + (e instanceof Error ? e.message : '未知错误'))
  } finally {
    fetching.value = false
  }
}

// ── History loading ──
async function loadHistory() {
  historyLoading.value = true
  try {
    const resp = await fetchApi.history(auth.ownerId, historyLimit.value, (historyPage.value - 1) * historyLimit.value)
    history.value = resp.records
    historyTotal.value = resp.total
  } catch (e) {
    console.error('Failed to load fetch history:', e)
  } finally {
    historyLoading.value = false
  }
}

function onHistoryPageChange(p: number) {
  historyPage.value = p
  loadHistory()
}

// ── Expand history row ──
async function toggleExpand(record: FetchRecord) {
  if (expandedId.value === record.id) {
    expandedId.value = null
    expandedDetail.value = null
    return
  }
  expandedId.value = record.id
  detailLoading.value = true
  try {
    const detail = await fetchApi.historyDetail(auth.ownerId, record.id)
    expandedDetail.value = detail
  } catch (e) {
    console.error('Failed to load fetch detail:', e)
    expandedDetail.value = null
  } finally {
    detailLoading.value = false
  }
}

// ── Format helpers ──
function fmtDate(iso: string): string {
  return iso ? iso.replace('T', ' ').substring(0, 19) : '-'
}

// ── Mount ──
onMounted(() => {
  loadHistory()
})
</script>

<template>
  <div class="fetch-page">
    <h2>论文抓取</h2>
    <p class="page-desc">从 arXiv 搜索、下载、解析并入库论文。</p>

    <!-- ═══ Section 1: Fetch Form ═══ -->
    <section class="section-card">
      <h3>抓取论文</h3>
      <div class="fetch-form">
        <div class="form-row">
          <label class="form-label" for="fetch-query">arXiv 查询语法</label>
          <input
            id="fetch-query"
            v-model="fetchQuery"
            class="form-input"
            placeholder="例如: cat:cs.AI AND ti:learning"
          />
        </div>
        <div class="form-row">
          <label class="form-label" for="fetch-n">最大结果数</label>
          <input
            id="fetch-n"
            v-model.number="fetchN"
            class="form-input"
            type="number"
            min="1"
            max="50"
            style="width: 120px"
          />
        </div>
        <button
          class="btn-primary fetch-btn"
          :disabled="fetching"
          @click="doFetch"
        >
          {{ fetching ? '抓取中…' : '一键抓取' }}
        </button>
      </div>
      <p class="form-hint">
        支持 <a href="https://info.arxiv.org/help/api/user-manual.html#query_details" target="_blank" rel="noopener">arXiv API 查询语法</a>，如 <code>au:delip</code>、<code>ti:transformer</code>、<code>cat:cs.CL</code> 等。
      </p>
    </section>

    <!-- ═══ Section 2: Result Display ═══ -->
    <section v-if="lastResult" class="section-card">
      <h3>抓取结果</h3>
      <div class="stat-row">
        <div class="stat-card stat-found">
          <span class="stat-number">{{ lastResult.total_found }}</span>
          <span class="stat-label">找到</span>
        </div>
        <div class="stat-card stat-fetched">
          <span class="stat-number">{{ lastResult.fetched }}</span>
          <span class="stat-label">成功入库</span>
        </div>
        <div class="stat-card stat-skipped">
          <span class="stat-number">{{ lastResult.skipped }}</span>
          <span class="stat-label">跳过</span>
        </div>
        <div class="stat-card stat-failed">
          <span class="stat-number">{{ lastResult.failed }}</span>
          <span class="stat-label">失败</span>
        </div>
      </div>

      <div v-if="lastResult.skipped_papers.length > 0" class="skipped-section">
        <button class="btn-text" @click="showSkipped = !showSkipped">
          {{ showSkipped ? '▾' : '▸' }} 跳过的论文 ({{ lastResult.skipped_papers.length }} 篇)
        </button>
        <ul v-if="showSkipped" class="skipped-list">
          <li v-for="sp in lastResult.skipped_papers" :key="sp.id">
            <a :href="`https://arxiv.org/abs/${sp.id}`" target="_blank" rel="noopener">{{ sp.id }}</a>
            <span v-if="sp.title"> — {{ sp.title }}</span>
          </li>
        </ul>
      </div>
    </section>

    <!-- ═══ Section 3: History Table ═══ -->
    <section class="section-card">
      <h3>抓取历史</h3>

      <div v-if="historyLoading" class="loading">加载中…</div>

      <EmptyState
        v-else-if="!history.length"
        title="暂无抓取记录"
        description="使用上方表单发起一次论文抓取"
      />

      <template v-else>
        <Pagination
          :page="historyPage"
          :total-pages="historyTotalPages"
          :total="historyTotal"
          @change="onHistoryPageChange"
        />

        <div class="history-table-wrap">
          <table class="history-table">
            <thead>
              <tr>
                <th>时间</th>
                <th>查询</th>
                <th>找到</th>
                <th>抓取</th>
                <th>跳过</th>
                <th>下载</th>
                <th>解析</th>
                <th>入库</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <template v-for="r in history" :key="r.id">
                <tr
                  class="history-row"
                  :class="{ expanded: expandedId === r.id }"
                  @click="toggleExpand(r)"
                >
                  <td class="cell-time">{{ fmtDate(r.created_at) }}</td>
                  <td class="cell-query" :title="r.query_text">{{ r.query_text }}</td>
                  <td class="cell-num">{{ r.total_found }}</td>
                  <td class="cell-num">{{ r.fetched }}</td>
                  <td class="cell-num">{{ r.skipped }}</td>
                  <td class="cell-num">
                    <span class="num-ok">{{ r.download_success }}</span>
                    <span v-if="r.download_failed" class="num-bad"> / {{ r.download_failed }}</span>
                  </td>
                  <td class="cell-num">
                    <span class="num-ok">{{ r.parse_success }}</span>
                    <span v-if="r.parse_failed" class="num-bad"> / {{ r.parse_failed }}</span>
                  </td>
                  <td class="cell-num">{{ r.ingested }}</td>
                  <td class="cell-expand">
                    <span class="expand-icon">{{ expandedId === r.id ? '▾' : '▸' }}</span>
                  </td>
                </tr>
                <tr v-if="expandedId === r.id" class="detail-row">
                  <td colspan="9">
                    <div v-if="detailLoading" class="loading-small">加载详情…</div>
                    <div v-else-if="expandedDetail" class="detail-content">
                      <div class="detail-grid">
                        <div class="detail-item">
                          <span class="detail-label">查询条件</span>
                          <span class="detail-value">{{ expandedDetail.query_text }}</span>
                        </div>
                        <div class="detail-item">
                          <span class="detail-label">最大结果</span>
                          <span class="detail-value">{{ expandedDetail.max_results }}</span>
                        </div>
                        <div class="detail-item">
                          <span class="detail-label">总共找到</span>
                          <span class="detail-value">{{ expandedDetail.total_found }}</span>
                        </div>
                        <div class="detail-item">
                          <span class="detail-label">成功抓取</span>
                          <span class="detail-value">{{ expandedDetail.fetched }}</span>
                        </div>
                        <div class="detail-item">
                          <span class="detail-label">跳过（去重）</span>
                          <span class="detail-value">{{ expandedDetail.skipped }}</span>
                        </div>
                        <div class="detail-item">
                          <span class="detail-label">下载成功</span>
                          <span class="detail-value">{{ expandedDetail.download_success }}</span>
                        </div>
                        <div class="detail-item">
                          <span class="detail-label">下载失败</span>
                          <span class="detail-value">{{ expandedDetail.download_failed }}</span>
                        </div>
                        <div class="detail-item">
                          <span class="detail-label">解析成功</span>
                          <span class="detail-value">{{ expandedDetail.parse_success }}</span>
                        </div>
                        <div class="detail-item">
                          <span class="detail-label">解析失败</span>
                          <span class="detail-value">{{ expandedDetail.parse_failed }}</span>
                        </div>
                        <div class="detail-item">
                          <span class="detail-label">最终入库</span>
                          <span class="detail-value">{{ expandedDetail.ingested }}</span>
                        </div>
                      </div>
                      <div v-if="expandedDetail.skipped_papers.length > 0" class="detail-skipped">
                        <h4>跳过的论文</h4>
                        <ul>
                          <li v-for="sp in expandedDetail.skipped_papers" :key="sp.id">
                            <a :href="`https://arxiv.org/abs/${sp.id}`" target="_blank" rel="noopener">{{ sp.id }}</a>
                            <span v-if="sp.title"> — {{ sp.title }}</span>
                          </li>
                        </ul>
                      </div>
                    </div>
                    <div v-else class="loading-small">无法加载详情</div>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>

        <Pagination
          :page="historyPage"
          :total-pages="historyTotalPages"
          :total="historyTotal"
          @change="onHistoryPageChange"
        />
      </template>
    </section>
  </div>
</template>

<style scoped>
.fetch-page {
  max-width: 1100px;
}

.page-desc {
  font-size: 14px;
  color: var(--color-body);
  margin-bottom: 20px;
}

/* ── Section card ── */
.section-card {
  background: var(--color-canvas);
  border: 1px solid var(--color-hairline);
  border-radius: var(--radius-md);
  padding: 24px;
  margin-bottom: 24px;
}

.section-card h3 {
  font-size: 16px;
  font-weight: 600;
  margin: 0 0 16px;
  color: var(--color-ink);
}

/* ── Fetch form ── */
.fetch-form {
  display: flex;
  gap: 16px;
  align-items: flex-end;
  flex-wrap: wrap;
}

.form-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.form-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--color-body);
}

.form-hint {
  font-size: 12px;
  color: var(--color-mute);
  margin: 12px 0 0;
}

.form-hint code {
  background: var(--color-surface);
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 12px;
}

.form-hint a {
  color: var(--color-primary);
}

.fetch-btn {
  height: 38px;
}

/* ── Stat row ── */
.stat-row {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}

.stat-card {
  flex: 1;
  min-width: 100px;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 16px 12px;
  border-radius: var(--radius-sm);
  background: var(--color-surface);
}

.stat-number {
  font-size: 28px;
  font-weight: 700;
  line-height: 1.2;
}

.stat-label {
  font-size: 13px;
  color: var(--color-mute);
  margin-top: 4px;
}

.stat-found .stat-number { color: var(--color-primary); }
.stat-fetched .stat-number { color: #16a34a; }
.stat-skipped .stat-number { color: #d97706; }
.stat-failed .stat-number { color: #dc2626; }

/* ── Skipped papers ── */
.skipped-section {
  margin-top: 16px;
}

.btn-text {
  background: none;
  border: none;
  color: var(--color-body);
  font-size: 14px;
  cursor: pointer;
  padding: 4px 0;
}

.btn-text:hover {
  color: var(--color-primary);
}

.skipped-list {
  margin: 8px 0 0;
  padding-left: 20px;
  font-size: 13px;
  color: var(--color-body);
}

.skipped-list li {
  margin-bottom: 4px;
}

.skipped-list a {
  color: var(--color-primary);
  font-family: monospace;
}

/* ── Loading ── */
.loading {
  text-align: center;
  padding: 48px 0;
  color: var(--color-mute);
}

.loading-small {
  text-align: center;
  padding: 16px;
  color: var(--color-mute);
  font-size: 13px;
}

/* ── History table ── */
.history-table-wrap {
  overflow-x: auto;
  margin: 8px 0;
}

.history-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.history-table th {
  text-align: left;
  padding: 10px 8px;
  font-weight: 600;
  color: var(--color-body);
  border-bottom: 2px solid var(--color-hairline);
  white-space: nowrap;
}

.history-table td {
  padding: 8px;
  border-bottom: 1px solid var(--color-hairline);
  vertical-align: middle;
}

.history-row {
  cursor: pointer;
  transition: background 0.1s;
}

.history-row:hover {
  background: var(--color-surface);
}

.history-row.expanded {
  background: var(--color-surface);
}

.cell-time {
  white-space: nowrap;
  font-size: 12px;
  color: var(--color-mute);
}

.cell-query {
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cell-num {
  text-align: center;
  white-space: nowrap;
}

.cell-expand {
  text-align: center;
  width: 32px;
}

.expand-icon {
  font-size: 12px;
  color: var(--color-mute);
}

.num-ok {
  color: #16a34a;
}

.num-bad {
  color: #dc2626;
}

/* ── Expanded detail row ── */
.detail-row td {
  padding: 0;
  border-bottom: 2px solid var(--color-hairline);
}

.detail-content {
  padding: 16px 24px;
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.detail-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.detail-label {
  font-size: 12px;
  color: var(--color-mute);
}

.detail-value {
  font-size: 14px;
  font-weight: 500;
  color: var(--color-ink);
}

.detail-skipped h4 {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-body);
  margin: 0 0 8px;
}

.detail-skipped ul {
  margin: 0;
  padding-left: 20px;
  font-size: 13px;
  color: var(--color-body);
}

.detail-skipped li {
  margin-bottom: 4px;
}

.detail-skipped a {
  color: var(--color-primary);
  font-family: monospace;
}
</style>
