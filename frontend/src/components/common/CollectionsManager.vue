<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useToastStore } from '@/stores/toast'
import { collectionsApi } from '@/api/client'
import type { Collection, Paper } from '@/api/types'

const auth = useAuthStore()
const toast = useToastStore()
const collections = ref<Collection[]>([])
const loading = ref(false)
const showCreate = ref(false)
const newName = ref('')
const newDesc = ref('')
const selectedCollection = ref<Collection | null>(null)
const collectionPapers = ref<Paper[]>([])

onMounted(() => loadCollections())

async function loadCollections() {
  try {
    const r = await collectionsApi.list(auth.ownerId)
    collections.value = r.collections || []
  } catch { /* ignore */ }
}

async function createCollection() {
  if (!newName.value.trim()) return
  try {
    const c = await collectionsApi.create(auth.ownerId, newName.value.trim(), newDesc.value.trim())
    collections.value.unshift(c)
    newName.value = ''
    newDesc.value = ''
    showCreate.value = false
    toast.success(`收藏夹「${c.name}」已创建`)
  } catch (e) {
    toast.error('创建失败: ' + (e instanceof Error ? e.message : ''))
  }
}

async function deleteCollection(col: Collection) {
  if (!confirm(`确定删除收藏夹「${col.name}」？`)) return
  try {
    await collectionsApi.delete(auth.ownerId, col.id)
    collections.value = collections.value.filter(c => c.id !== col.id)
    if (selectedCollection.value?.id === col.id) {
      selectedCollection.value = null
      collectionPapers.value = []
    }
    toast.success('已删除')
  } catch (e) {
    toast.error('删除失败')
  }
}

async function viewCollection(col: Collection) {
  selectedCollection.value = col
  loading.value = true
  try {
    const r = await collectionsApi.listPapers(auth.ownerId, col.id, 100, 0)
    collectionPapers.value = r.papers || []
  } catch {
    collectionPapers.value = []
  } finally {
    loading.value = false
  }
}

// eslint-disable-next-line @typescript-eslint/no-unused-vars
async function addToCollection(paperId: number) {
  if (!selectedCollection.value) return
  try {
    await collectionsApi.addPaper(auth.ownerId, selectedCollection.value.id, paperId)
    toast.success('已添加到收藏夹')
    viewCollection(selectedCollection.value)
  } catch (e) {
    toast.error('添加失败')
  }
}
</script>

<template>
  <div class="collections-panel">
    <details>
      <summary class="panel-summary">
        收藏夹
        <span v-if="collections.length" class="count">{{ collections.length }}</span>
      </summary>

      <div class="panel-body">
        <!-- Create -->
        <div v-if="!showCreate" class="mb-2">
          <button class="btn-secondary" style="height:32px;font-size:13px" @click="showCreate = true">+ 新建收藏夹</button>
        </div>
        <div v-else class="create-form mb-2">
          <input v-model="newName" class="form-input" placeholder="收藏夹名称" @keyup.enter="createCollection" style="height:32px" />
          <input v-model="newDesc" class="form-input" placeholder="描述（可选）" style="height:32px" />
          <div class="create-actions">
            <button class="btn-primary" style="height:32px;font-size:13px" @click="createCollection">创建</button>
            <button class="btn-secondary" style="height:32px;font-size:13px" @click="showCreate = false">取消</button>
          </div>
        </div>

        <!-- Collection list -->
        <div v-if="!collections.length && !showCreate" class="empty-hint">暂无收藏夹</div>
        <div v-for="col in collections" :key="col.id" class="collection-item" :class="{ active: selectedCollection?.id === col.id }">
          <div class="col-info" @click="viewCollection(col)">
            <div class="col-name">{{ col.name }}</div>
            <div class="col-meta">{{ col.paper_count }} 篇论文</div>
          </div>
          <button class="col-delete" @click.stop="deleteCollection(col)" title="删除">X</button>
        </div>

        <!-- Collection papers -->
        <div v-if="selectedCollection" class="col-papers">
          <h4>{{ selectedCollection.name }} · {{ collectionPapers.length }} 篇</h4>
          <div v-if="loading">加载中…</div>
          <div v-if="!loading && !collectionPapers.length" class="empty-hint">暂无论文</div>
          <div v-for="p in collectionPapers" :key="p.id" class="col-paper-item">
            <span class="col-paper-title">{{ (p.title || p.arxiv_id).slice(0, 50) }}</span>
            <span class="col-paper-id">{{ p.arxiv_id }}</span>
          </div>
        </div>
      </div>
    </details>
  </div>
</template>

<style scoped>
.collections-panel {
  background: var(--color-canvas);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-card);
  margin-bottom: 16px;
}
.panel-summary {
  padding: 14px 20px;
  font-size: 14px; font-weight: 600; color: var(--color-ink);
  cursor: pointer; display: flex; align-items: center; gap: 8px;
}
.count { font-size: 12px; color: var(--color-mute); }
.panel-body { padding: 0 20px 16px; }
.mb-2 { margin-bottom: 8px; }
.create-form { display: flex; flex-direction: column; gap: 8px; }
.create-actions { display: flex; gap: 8px; }
.collection-item {
  display: flex; align-items: center; justify-content: space-between;
  padding: 8px 10px; border-radius: var(--radius-sm);
  cursor: pointer; transition: background 0.1s;
}
.collection-item:hover { background: var(--color-canvas-soft); }
.collection-item.active { background: var(--color-canvas-soft-2); }
.col-info { flex: 1; }
.col-name { font-size: 14px; font-weight: 500; color: var(--color-ink); }
.col-meta { font-size: 12px; color: var(--color-mute); }
.col-delete {
  background: none; border: none; cursor: pointer;
  font-size: 14px; opacity: 0; transition: opacity 0.1s;
}
.collection-item:hover .col-delete { opacity: 1; }
.col-papers { margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--color-hairline); }
.col-papers h4 { font-size: 14px; margin: 0 0 8px; color: var(--color-ink); }
.col-paper-item {
  display: flex; justify-content: space-between; align-items: center;
  padding: 6px 8px; font-size: 13px; border-radius: var(--radius-xs);
}
.col-paper-item:hover { background: var(--color-canvas-soft); }
.col-paper-title { color: var(--color-ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.col-paper-id { color: var(--color-mute); flex-shrink: 0; margin-left: 8px; font-size: 11px; }
.empty-hint { font-size: 13px; color: var(--color-mute); padding: 8px 0; }
</style>
