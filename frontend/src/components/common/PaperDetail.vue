<script setup lang="ts">
import { ref, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { papersApi } from '@/api/client'
import type { Paper, PaperChunk } from '@/api/types'
import ThinkingIndicator from './ThinkingIndicator.vue'

interface Section {
  title: string
  content: string
  subsections: { title: string; content: string }[]
}

const props = defineProps<{
  paper: Paper
  visible: boolean
}>()

const emit = defineEmits<{
  close: []
}>()

const auth = useAuthStore()
const tab = ref<'chunks' | 'original' | 'metadata' | 'pdf'>('chunks')
const chunks = ref<PaperChunk[]>([])
const sections = ref<Section[]>([])
const loading = ref(false)
const error = ref('')

watch(() => props.visible, async (v) => {
  if (v && props.paper) {
    tab.value = 'chunks'
    chunks.value = []
    sections.value = []
    error.value = ''
    await loadChunks()
  }
})

async function loadChunks() {
  loading.value = true
  error.value = ''
  try {
    const r = await papersApi.chunks(auth.ownerId, props.paper.arxiv_id)
    chunks.value = r.chunks || []
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

async function loadContent() {
  if (sections.value.length) return
  loading.value = true
  error.value = ''
  try {
    const resp = await fetch(`/api/papers/${props.paper.arxiv_id}/content`)
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const data = await resp.json()
    sections.value = data.sections || []
  } catch (e) {
    error.value = e instanceof Error ? e.message : '无法加载原文'
  } finally {
    loading.value = false
  }
}

function switchTab(t: typeof tab.value) {
  tab.value = t
  if (t === 'original') loadContent()
}

function pdfUrl(): string {
  return papersApi.pdfUrl(auth.ownerId, props.paper.arxiv_id)
}
</script>

<template>
  <Teleport to="body">
    <div v-if="visible" class="modal-overlay" @click.self="$emit('close')">
      <div class="modal-card">
        <div class="modal-header">
          <div>
            <h3>{{ paper.title || paper.arxiv_id }}</h3>
            <p class="modal-authors">{{ paper.authors || '未知作者' }}</p>
          </div>
          <button class="modal-close" @click="$emit('close')">&times;</button>
        </div>

        <div class="modal-tabs">
          <button :class="{ active: tab === 'chunks' }" @click="switchTab('chunks')">分块内容</button>
          <button :class="{ active: tab === 'original' }" @click="switchTab('original')">原文</button>
          <button :class="{ active: tab === 'pdf' }" @click="switchTab('pdf')">PDF</button>
          <button :class="{ active: tab === 'metadata' }" @click="switchTab('metadata')">元数据</button>
        </div>

        <div class="modal-body">
          <ThinkingIndicator v-if="loading" text="加载中…" />
          <div v-if="error && !loading" class="error-msg">{{ error }}</div>

          <!-- Chunks -->
          <div v-if="tab === 'chunks' && !loading">
            <div v-if="!chunks.length" class="empty">暂无分块数据，请先入库</div>
            <div v-for="(c, i) in chunks.slice(0, 30)" :key="c.id || i" class="chunk-item">
              <div class="chunk-header">
                Chunk {{ i + 1 }}
                <span v-if="c.metadata?.section_title"> | {{ c.metadata.section_title }}</span>
                <span v-if="c.metadata?.page"> | p.{{ c.metadata.page }}</span>
              </div>
              <div class="chunk-text">{{ (c.document || '').slice(0, 800) }}{{ (c.document || '').length > 800 ? '…' : '' }}</div>
            </div>
            <div v-if="chunks.length > 30" class="chunk-more">… 仅显示前 30 个分块（共 {{ chunks.length }} 个）</div>
          </div>

          <!-- Original Text (parsed JSON sections) -->
          <div v-if="tab === 'original' && !loading">
            <div v-if="!sections.length" class="empty">暂无解析数据。请先通过 arXiv 管道下载并解析 PDF。</div>
            <div v-for="(sec, i) in sections" :key="i" class="section-block">
              <details :open="i < 3">
                <summary class="section-title">{{ sec.title || 'Untitled' }}</summary>
                <div class="section-content">{{ sec.content?.slice(0, 2000) }}{{ (sec.content || '').length > 2000 ? '…' : '' }}</div>
                <div v-if="(sec.content || '').length > 2000" class="truncate-note">… 内容过长，仅显示前 2000 字符（共 {{ sec.content.length }} 字符）</div>
                <div v-for="(sub, j) in sec.subsections" :key="j" class="subsection">
                  <div class="subsection-title">{{ sub.title }}</div>
                  <div class="subsection-content">{{ sub.content?.slice(0, 1000) }}{{ (sub.content || '').length > 1000 ? '…' : '' }}</div>
                </div>
              </details>
            </div>
          </div>

          <!-- PDF Viewer -->
          <div v-if="tab === 'pdf'" class="pdf-viewer">
            <iframe :src="pdfUrl()" class="pdf-frame" title="PDF Preview"></iframe>
            <div class="pdf-fallback">
              <a :href="pdfUrl()" target="_blank" class="btn-secondary">在新窗口打开 PDF</a>
            </div>
          </div>

          <!-- Metadata -->
          <div v-if="tab === 'metadata'" class="metadata-view">
            <table>
              <tr><td class="key">arXiv ID</td><td>{{ paper.arxiv_id }}</td></tr>
              <tr><td class="key">标题</td><td>{{ paper.title }}</td></tr>
              <tr><td class="key">作者</td><td>{{ paper.authors }}</td></tr>
              <tr><td class="key">摘要</td><td class="abstract-cell">{{ paper.abstract }}</td></tr>
              <tr><td class="key">发表日期</td><td>{{ paper.published }}</td></tr>
              <tr><td class="key">来源</td><td>{{ paper.source }}</td></tr>
              <tr><td class="key">入库状态</td><td><span :class="`badge badge-${paper.ingest_status === 'ingested' ? 'success' : paper.ingest_status === 'pending' ? 'warning' : 'error'}`">{{ { ingested: '已入库', pending: '待处理', failed: '失败' }[paper.ingest_status] }}</span></td></tr>
              <tr><td class="key">分块数</td><td>{{ paper.chunk_count }}</td></tr>
            </table>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.modal-overlay {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.4);
  display: flex; align-items: center; justify-content: center;
  z-index: 150; backdrop-filter: blur(2px);
}
.modal-card {
  background: var(--color-canvas);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-modal);
  width: 900px; max-width: 95vw; max-height: 88vh;
  display: flex; flex-direction: column;
}
.modal-header {
  display: flex; justify-content: space-between; align-items: flex-start;
  padding: 24px 24px 16px; border-bottom: 1px solid var(--color-hairline);
}
.modal-header h3 { margin: 0; font-size: 18px; line-height: 1.4; }
.modal-authors { margin: 4px 0 0; font-size: 13px; color: var(--color-mute); }
.modal-close {
  background: none; border: 1px solid var(--color-hairline);
  border-radius: var(--radius-sm); width: 32px; height: 32px;
  cursor: pointer; font-size: 16px; color: var(--color-mute);
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0; margin-left: 12px;
}
.modal-close:hover { color: var(--color-ink); border-color: var(--color-hairline-strong); }
.modal-tabs {
  display: flex; border-bottom: 1px solid var(--color-hairline);
  padding: 0 24px; overflow-x: auto;
}
.modal-tabs button {
  padding: 10px 20px; background: none; border: none;
  font-size: 14px; font-weight: 500; color: var(--color-mute);
  cursor: pointer; border-bottom: 2px solid transparent;
  white-space: nowrap; transition: all 0.15s;
  flex-shrink: 0;
}
.modal-tabs button:hover { color: var(--color-ink); }
.modal-tabs button.active { color: var(--color-ink); border-bottom-color: var(--color-ink); }
.modal-body { flex: 1; overflow-y: auto; overflow-x: hidden; padding: 20px 24px; min-width: 0; }

/* Chunks */
.chunk-item { padding: 12px 0; border-bottom: 1px solid var(--color-hairline); }
.chunk-header { font-size: 12px; font-weight: 600; color: var(--color-mute); margin-bottom: 6px; }
.chunk-text { font-size: 14px; line-height: 1.6; color: var(--color-body); white-space: pre-wrap; word-break: break-word; overflow-wrap: break-word; }
.chunk-more { text-align: center; padding: 16px; font-size: 13px; color: var(--color-mute); }

/* Original text sections */
.section-block { margin-bottom: 8px; border: 1px solid var(--color-hairline); border-radius: var(--radius-sm); }
.section-block details { padding: 0; }
.section-title {
  font-size: 15px; font-weight: 600; color: var(--color-ink);
  padding: 12px 16px; cursor: pointer; background: var(--color-canvas-soft);
  border-radius: var(--radius-sm);
}
.section-content {
  padding: 12px 16px; font-size: 14px; line-height: 1.7;
  color: var(--color-body); white-space: pre-wrap;
}
.truncate-note { padding: 0 16px 8px; font-size: 12px; color: var(--color-mute); }
.subsection { padding: 0 16px 12px; }
.subsection-title { font-size: 14px; font-weight: 600; color: var(--color-ink); margin-bottom: 4px; }
.subsection-content { font-size: 13px; line-height: 1.6; color: var(--color-body); white-space: pre-wrap; }

/* PDF */
.pdf-viewer { display: flex; flex-direction: column; height: 100%; min-height: 500px; }
.pdf-frame { flex: 1; width: 100%; border: 1px solid var(--color-hairline); border-radius: var(--radius-sm); }
.pdf-fallback { text-align: center; padding: 12px; }

/* Metadata */
.metadata-view table { width: 100%; border-collapse: collapse; }
.metadata-view td { padding: 8px 12px; border-bottom: 1px solid var(--color-hairline); font-size: 14px; vertical-align: top; }
.metadata-view .key { font-weight: 600; color: var(--color-mute); width: 100px; white-space: nowrap; }
.abstract-cell { line-height: 1.6; color: var(--color-body); }

.empty { color: var(--color-mute); padding: 24px 0; text-align: center; }
.error-msg { padding: 12px; background: var(--color-error-soft); color: var(--color-error-deep); border-radius: var(--radius-sm); }
</style>
