<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { storeApi, summaryApi, papersApi } from '@/api/client'
import ChatBubble from '@/components/common/ChatBubble.vue'
import EmptyState from '@/components/common/EmptyState.vue'

const auth = useAuthStore()
const tab = ref<'summarize' | 'survey' | 'recommend'>('summarize')
const papers = ref<{ arxiv_id: string; title: string }[]>([])
const selectedPaper = ref('')
const lang = ref<'zh' | 'en'>('zh')
const result = ref('')
const loading = ref(false)

// Survey
const topic = ref('')
const surveyTopK = ref(15)

// Recommend
const recTopK = ref(5)
const similar = ref<{ arxiv_id: string; title: string; score: number; shared_chunks: number }[]>([])

onMounted(async () => {
  try {
    papers.value = await storeApi.papers(auth.ownerId)
  } catch { /* */ }
})

async function doSummarize() {
  if (!selectedPaper.value) return
  loading.value = true
  result.value = ''
  try {
    const r = await summaryApi.summarize(auth.ownerId, selectedPaper.value, lang.value)
    result.value = r.summary
  } catch (e) { console.error(e) }
  finally { loading.value = false }
}

async function doSurvey() {
  if (!topic.value.trim()) return
  loading.value = true
  result.value = ''
  try {
    const r = await summaryApi.survey(auth.ownerId, topic.value, surveyTopK.value, lang.value)
    result.value = r.survey
  } catch (e) { console.error(e) }
  finally { loading.value = false }
}

async function doRecommend() {
  if (!selectedPaper.value) return
  loading.value = true
  similar.value = []
  try {
    const r = await papersApi.recommend(auth.ownerId, selectedPaper.value, recTopK.value)
    similar.value = r.similar
  } catch (e) { console.error(e) }
  finally { loading.value = false }
}

</script>

<template>
  <div class="summary-page">
    <h2>摘要 & 综述</h2>
    <p class="page-desc">生成论文摘要、多论文综述，或基于向量相似度推荐相关研究。</p>

    <div class="tabs">
      <button :class="{ active: tab === 'summarize' }" @click="tab = 'summarize'">论文摘要</button>
      <button :class="{ active: tab === 'survey' }" @click="tab = 'survey'">综述生成</button>
      <button :class="{ active: tab === 'recommend' }" @click="tab = 'recommend'">相似推荐</button>
    </div>


    <EmptyState v-if="!papers.length" title="暂无论文" description="请先导入论文数据" />

    <div v-else class="tab-content">
      <!-- Summarize -->
      <div v-if="tab === 'summarize'" class="form-section">
        <select v-model="selectedPaper" class="form-input">
          <option value="">选择论文…</option>
          <option v-for="p in papers" :key="p.arxiv_id" :value="p.arxiv_id">
            {{ p.arxiv_id }} — {{ (p.title || '').slice(0, 60) }}
          </option>
        </select>
        <select v-model="lang" class="form-input" style="width:auto">
          <option value="zh">中文</option>
          <option value="en">English</option>
        </select>
        <button class="btn-primary" :disabled="!selectedPaper || loading" @click="doSummarize">
          {{ loading ? '生成中…' : '生成摘要' }}
        </button>
      </div>

      <!-- Survey -->
      <div v-if="tab === 'survey'" class="form-section">
        <input v-model="topic" class="form-input" placeholder="搜索主题，如：spatial reasoning, VLM" />
        <select v-model.number="surveyTopK" class="form-input" style="width:auto">
          <option :value="10">10</option>
          <option :value="15">15</option>
          <option :value="20">20</option>
          <option :value="30">30</option>
          <option :value="50">50</option>
        </select>
        <select v-model="lang" class="form-input" style="width:auto">
          <option value="zh">中文</option>
          <option value="en">English</option>
        </select>
        <button class="btn-primary" :disabled="!topic.trim() || loading" @click="doSurvey">
          {{ loading ? '生成中…' : '生成综述' }}
        </button>
      </div>

      <!-- Recommend -->
      <div v-if="tab === 'recommend'" class="form-section">
        <select v-model="selectedPaper" class="form-input">
          <option value="">选择论文…</option>
          <option v-for="p in papers" :key="p.arxiv_id" :value="p.arxiv_id">
            {{ p.arxiv_id }} — {{ (p.title || '').slice(0, 60) }}
          </option>
        </select>
        <span>推荐数量: {{ recTopK }}</span>
        <input v-model.number="recTopK" type="range" min="2" max="15" />
        <button class="btn-primary" :disabled="!selectedPaper || loading" @click="doRecommend">
          查找相似论文
        </button>
      </div>

      <!-- Results -->
      <div v-if="result" class="result-area mt-4">
        <ChatBubble :content="result" role="assistant" :is-markdown="true" />
      </div>

      <div v-if="similar.length" class="similar-list">
        <div v-for="(s, i) in similar" :key="s.arxiv_id" class="paper-card" style="margin-bottom:12px">
          <div class="paper-title">[{{ i + 1 }}] {{ s.title }}</div>
          <div class="paper-meta">
            <span>{{ s.arxiv_id }}</span>
            <span>相似度 {{ s.score.toFixed(4) }}</span>
            <span>{{ s.shared_chunks }} 共同片段</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.summary-page { max-width: 900px; }
.page-desc { font-size: 14px; color: var(--color-body); margin-bottom: 20px; }
.tabs { display: flex; gap: 0; margin-bottom: 24px; border-bottom: 1px solid var(--color-hairline); }
.tabs button {
  padding: 10px 20px; background: none; border: none; font-size: 14px; font-weight: 500;
  color: var(--color-mute); cursor: pointer; border-bottom: 2px solid transparent;
  transition: all 0.15s;
}
.tabs button:hover { color: var(--color-ink); }
.tabs button.active { color: var(--color-ink); border-bottom-color: var(--color-ink); }
.form-section { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin-bottom: 24px; }
.result-area { background: var(--color-canvas); border-radius: var(--radius-lg); padding: 24px; }
.similar-list { margin-top: 16px; }
.paper-title { font-size: 16px; font-weight: 600; color: var(--color-ink); margin-bottom: 4px; }
.paper-meta { font-size: 12px; color: var(--color-mute); display: flex; gap: 12px; }
.mt-4 { margin-top: 16px; }
</style>
