<script setup lang="ts">
import { ref, nextTick } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { ragApi } from '@/api/client'
import { streamSSE } from '@/composables/useStreaming'
import ChatBubble from '@/components/common/ChatBubble.vue'
import ThinkingIndicator from '@/components/common/ThinkingIndicator.vue'

const auth = useAuthStore()
const query = ref('')
const topK = ref(5)
const lang = ref<'zh' | 'en'>('zh')
const temperature = ref(0.3)
const globalMode = ref(false)
const loading = ref(false)
const answer = ref('')
const sources = ref<{ idx: number; title: string; excerpt: string }[]>([])
const error = ref('')

const examples = [
  '总结 RLBench 相关论文的核心方法',
  '对比 SpatialClaw 和传统 VLM 方法',
  '哪些论文引用了 2606.13673v1？',
  '推荐与这篇论文相似的研究',
]

function useExample(ex: string) {
  query.value = ex
}

async function search() {
  if (!query.value.trim()) return
  loading.value = true
  error.value = ''
  answer.value = ''
  sources.value = []

  try {
    if (globalMode.value) {
      const result = await ragApi.query(auth.ownerId, query.value, topK.value, lang.value)
      answer.value = result.answer || ''
    } else {
      // Retrieve + stream answer
      const retrieveResult = await ragApi.retrieve(auth.ownerId, query.value, topK.value)
      const hits = retrieveResult.hits || []
      sources.value = hits.map((h, i) => ({
        idx: i + 1,
        title: (h.metadata?.section_title as string) || (h.metadata?.title as string) || (h.metadata?.arxiv_id as string) || '?',
        excerpt: (h.document || '').slice(0, 250) + (h.document?.length > 250 ? '…' : ''),
      }))

      const resp = await ragApi.queryStream(auth.ownerId, query.value, topK.value, lang.value, temperature.value)
      for await (const token of streamSSE(resp)) {
        answer.value += token
        await nextTick()
      }
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : '请求失败'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="qa-page">
    <div class="hero-search">
      <h1>用 AI 读懂每一篇论文</h1>
      <p>基于 RAG 的学术论文智能问答 — 搜索、理解、对比，像和专家对话一样</p>
    </div>

    <div class="qa-input-area">
      <div class="input-row">
        <textarea
          v-model="query"
          class="form-input qa-textarea"
          placeholder="试试问：SpatialClaw 的核心创新是什么？"
          rows="2"
          @keyup.ctrl.enter="search"
        ></textarea>
      </div>

      <div class="controls-row">
        <div class="control-group">
          <label>精度</label>
          <select v-model.number="topK" class="form-input" style="width:auto">
            <option :value="3">3</option>
            <option :value="5">5</option>
            <option :value="10">10</option>
            <option :value="20">20</option>
          </select>
        </div>
        <div class="control-group">
          <label>语言</label>
          <select v-model="lang" class="form-input" style="width:auto">
            <option value="zh">中文</option>
            <option value="en">English</option>
          </select>
        </div>
        <div class="control-group">
          <label>温度 {{ temperature }}</label>
          <input v-model.number="temperature" type="range" min="0" max="1.5" step="0.1" />
        </div>
        <div class="control-group">
          <label class="checkbox-label">
            <input v-model="globalMode" type="checkbox" />
            全局分析模式
          </label>
        </div>
        <button class="btn-primary" :disabled="!query.trim() || loading" @click="search">
          {{ loading ? '搜索中…' : '搜索回答' }}
        </button>
      </div>
    </div>

    <div v-if="error" class="error-msg">{{ error }}</div>

    <div v-if="loading" class="loading-area">
      <ThinkingIndicator text="检索相关论文片段…" />
    </div>

    <div v-if="sources.length && answer" class="sources-area">
      <details>
        <summary>引用论文片段（{{ sources.length }} 条）</summary>
        <div v-for="s in sources" :key="s.idx" class="source-item">
          <div class="source-title">[{{ s.idx }}] {{ s.title }}</div>
          <div class="source-excerpt">{{ s.excerpt }}</div>
        </div>
      </details>
    </div>

    <div v-if="answer" class="answer-area">
      <h3>回答</h3>
      <ChatBubble :content="answer" role="assistant" :is-markdown="true" />
    </div>

    <div v-if="!answer && !loading" class="examples-area">
      <h3>试试这些问题</h3>
      <div class="examples-grid">
        <button v-for="ex in examples" :key="ex" class="example-btn" @click="useExample(ex)">
          {{ ex }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.qa-page { max-width: 900px; }
.hero-search { text-align: center; padding: 32px 0; }
.hero-search h1 { font-size: 32px; margin-bottom: 8px; }
.hero-search p { font-size: 16px; color: var(--color-body); }
.qa-input-area {
  background: var(--color-canvas);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
  padding: 24px;
  margin-bottom: 24px;
}
.qa-textarea {
  height: auto;
  min-height: 68px;
  resize: vertical;
  font-size: 15px;
  padding: 12px;
}
.controls-row {
  display: flex;
  align-items: flex-end;
  gap: 16px;
  margin-top: 16px;
  flex-wrap: wrap;
}
.control-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.control-group label {
  font-size: 12px;
  color: var(--color-mute);
  font-weight: 500;
}
.checkbox-label {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  font-size: 13px;
  color: var(--color-body);
}
.error-msg {
  padding: 12px 16px;
  background: var(--color-error-soft);
  color: var(--color-error-deep);
  border-radius: var(--radius-sm);
  font-size: 14px;
  margin-bottom: 16px;
}
.loading-area { margin-bottom: 16px; }
.sources-area {
  background: var(--color-canvas);
  border-radius: var(--radius-md);
  padding: 16px 24px;
  margin-bottom: 16px;
}
.sources-area summary {
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  color: var(--color-body);
}
.source-item {
  padding: 10px 0;
  border-bottom: 1px solid var(--color-hairline);
}
.source-title { font-size: 13px; font-weight: 600; color: var(--color-ink); }
.source-excerpt { font-size: 12px; color: var(--color-mute); margin-top: 4px; }
.answer-area { margin-top: 8px; }
.answer-area h3 { margin-bottom: 12px; }
.examples-area { margin-top: 32px; }
.examples-area h3 { font-size: 14px; color: var(--color-mute); margin-bottom: 12px; }
.examples-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
}
.example-btn {
  padding: 12px 16px;
  background: var(--color-canvas);
  border: 1px solid var(--color-hairline);
  border-radius: var(--radius-sm);
  font-size: 13px;
  color: var(--color-body);
  cursor: pointer;
  text-align: left;
  transition: all 0.15s;
}
.example-btn:hover {
  border-color: var(--color-ink);
  color: var(--color-ink);
}
</style>
