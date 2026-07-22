<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { papersApi, storeApi } from '@/api/client'
import type { Paper } from '@/api/types'
import PaperCard from '@/components/common/PaperCard.vue'
import PaperDetail from '@/components/common/PaperDetail.vue'
import CollectionsManager from '@/components/common/CollectionsManager.vue'
import Pagination from '@/components/common/Pagination.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { useToastStore } from '@/stores/toast'

const auth = useAuthStore()
const toast = useToastStore()
const papers = ref<Paper[]>([])
const total = ref(0)
const page = ref(1)
const limit = ref(20)
const keyword = ref('')
const author = ref('')
const yearFrom = ref('')
const yearTo = ref('')
const statusFilter = ref('')
const sortBy = ref('created_at')
const loading = ref(false)
const totalPages = ref(1)
const totalAll = ref(0)

// Pending
const pendingCount = ref(0)

// Paper detail modal
const selectedPaper = ref<Paper | null>(null)

function openDetail(paper: Paper) {
  selectedPaper.value = paper
}

async function loadPapers() {
  loading.value = true
  try {
    const hasFilter = keyword.value || author.value || yearFrom.value || yearTo.value || statusFilter.value
    if (hasFilter) {
      const result = await papersApi.search(auth.ownerId, {
        keyword: keyword.value,
        author: author.value,
        year_from: yearFrom.value,
        year_to: yearTo.value,
        status: statusFilter.value,
        sort_by: sortBy.value,
        limit: 1000,
      })
      const all = result.papers
      totalPages.value = Math.max(1, Math.ceil(all.length / limit.value))
      papers.value = all.slice((page.value - 1) * limit.value, page.value * limit.value)
      total.value = all.length
    } else {
      const result = await papersApi.list(auth.ownerId, limit.value, (page.value - 1) * limit.value)
      papers.value = result.papers
      total.value = result.total
      totalPages.value = Math.max(1, Math.ceil(result.total / limit.value))
    }
    // Get all-papers count
    const allResult = await papersApi.list(auth.ownerId, 1, 0)
    totalAll.value = allResult.total
  } catch (e) {
    console.error('Failed to load papers:', e)
  } finally {
    loading.value = false
  }
}

async function checkPending() {
  try {
    const r = await papersApi.search(auth.ownerId, { status: 'pending', limit: 200 })
    pendingCount.value = r.total
  } catch { /* ignore */ }
}

async function processPending() {
  try {
    const result = await arxivApi.processPending(auth.ownerId)
    toast.success(`处理完成: ${result.total ?? 0} 篇论文, 入库 ${result.ingested ?? 0} 篇`)
    await loadPapers()
    await checkPending()
  } catch (e) {
    toast.error('处理失败: ' + (e instanceof Error ? e.message : '未知错误'))
    console.error(e)
  }
}

async function doIngest() {
  try {
    const result = await storeApi.ingest(auth.ownerId)
    toast.success(`入库完成: ${result.papers} 篇论文, ${result.chunks} 个分块`)
    await loadPapers()
    await checkPending()
  } catch (e) {
    toast.error('入库失败: ' + (e instanceof Error ? e.message : '未知错误'))
    console.error(e)
  }
}

onMounted(() => {
  loadPapers()
  checkPending()
})
</script>

<template>
  <div class="library-page">
    <h2>论文库</h2>
    <p class="page-desc">浏览、搜索和管理已入库的学术论文。</p>

    <!-- Quick Actions -->
    <div class="actions-bar">
      <button class="btn-secondary" @click="doIngest">重新入库</button>
      <router-link to="/fetch" class="btn-secondary" style="text-decoration:none">前往论文抓取 →</router-link>
    </div>

    <div v-if="pendingCount > 0" class="pending-bar">
      <span>{{ pendingCount }} 篇待处理</span>
      <button class="btn-primary" @click="processPending">处理</button>
    </div>

    <!-- Collections -->
    <CollectionsManager />

    <!-- Search & Filter -->
    <div class="filter-bar">
      <input v-model="keyword" class="form-input" placeholder="搜索论文…" @keyup.enter="page=1;loadPapers()" />
      <input v-model="author" class="form-input" placeholder="作者" style="max-width:140px" />
      <input v-model="yearFrom" class="form-input" placeholder="年份从" style="max-width:80px" />
      <input v-model="yearTo" class="form-input" placeholder="年至" style="max-width:80px" />
      <select v-model="statusFilter" class="form-input" style="max-width:100px">
        <option value="">全部</option>
        <option value="ingested">已入库</option>
        <option value="pending">待处理</option>
        <option value="failed">失败</option>
      </select>
      <select v-model="sortBy" class="form-input" style="max-width:90px">
        <option value="created_at">入库</option>
        <option value="title">标题</option>
        <option value="published">日期</option>
      </select>
      <select v-model.number="limit" class="form-input" style="max-width:70px">
        <option :value="10">10</option>
        <option :value="20">20</option>
        <option :value="50">50</option>
        <option :value="100">100</option>
      </select>
      <button class="btn-primary" @click="page=1;loadPapers()">搜索</button>
    </div>

    <!-- Results -->
    <div v-if="loading" class="loading">加载中…</div>
    <EmptyState v-else-if="!papers.length" title="暂无论文" description="去 arXiv 抓取或导入本地论文" />

    <div v-else>
      <Pagination :page="page" :total-pages="totalPages" :total="total" @change="p => { page = p; loadPapers() }" />
      <div class="paper-list">
        <PaperCard v-for="p in papers" :key="p.id" :paper="p" :show-abstract="true" @click="openDetail(p)" />
      </div>
      <Pagination :page="page" :total-pages="totalPages" :total="total" @change="p => { page = p; loadPapers() }" />
    </div>

    <PaperDetail :paper="selectedPaper!" :visible="!!selectedPaper" @close="selectedPaper = null" />
  </div>
</template>

<style scoped>
.library-page { max-width: 1100px; }
.page-desc { font-size: 14px; color: var(--color-body); margin-bottom: 20px; }
.actions-bar { display: flex; gap: 12px; align-items: center; margin-bottom: 16px; flex-wrap: wrap; }

.pending-bar {
  display: flex; align-items: center; gap: 12px;
  padding: 10px 16px; background: #fef3c7; border-radius: var(--radius-sm);
  margin-bottom: 16px; font-size: 14px;
}
.filter-bar {
  display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; align-items: center;
}
.paper-list { display: flex; flex-direction: column; gap: 12px; }
.loading { text-align: center; padding: 48px 0; color: var(--color-mute); }
</style>
