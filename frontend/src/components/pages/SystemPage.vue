<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { storeApi, cacheApi } from '@/api/client'
import type { StoreStats, CacheStats } from '@/api/types'

const auth = useAuthStore()
const tab = ref<'status' | 'backup' | 'config'>('status')
const storeStats = ref<StoreStats>({ count: 0 })
const cacheStats = ref<CacheStats | null>(null)

onMounted(async () => {
  try {
    const [s, c] = await Promise.all([
      storeApi.stats(auth.ownerId),
      cacheApi.stats(auth.ownerId),
    ])
    storeStats.value = s
    cacheStats.value = c
  } catch { /* */ }
})

async function clearCache() {
  try { await cacheApi.clear(auth.ownerId, 'all'); location.reload() }
  catch (e) { console.error(e) }
}

async function doBackup() {
  try {
    const r = await storeApi.backup(auth.ownerId)
    alert(`已备份: ${(r as { backup_name: string }).backup_name || 'ok'}`)
  } catch (e) { console.error(e) }
}
</script>

<template>
  <div class="system-page">
    <h2>系统设置</h2>
    <div class="tabs">
      <button :class="{ active: tab === 'status' }" @click="tab = 'status'">状态</button>
      <button :class="{ active: tab === 'backup' }" @click="tab = 'backup'">备份</button>
      <button :class="{ active: tab === 'config' }" @click="tab = 'config'">配置</button>
    </div>

    <div v-if="tab === 'status'" class="tab-content">
      <div class="stat-grid">
        <div class="stat-card">
          <h3>向量库</h3>
          <div class="metric-big">{{ storeStats.count }}</div>
          <div class="metric-sub">chunks</div>
          <pre class="json-dump">{{ JSON.stringify(storeStats, null, 2) }}</pre>
        </div>
        <div v-if="cacheStats" class="stat-card">
          <h3>缓存</h3>
          <div class="cache-metrics">
            <div class="cache-item">
              <span>LLM 命中率</span>
              <strong>{{ cacheStats.llm.hit_rate_pct || (cacheStats.llm.hit_rate * 100).toFixed(1) + '%' }}</strong>
            </div>
            <div class="cache-item">
              <span>Embed 命中率</span>
              <strong>{{ cacheStats.embed.hit_rate_pct || (cacheStats.embed.hit_rate * 100).toFixed(1) + '%' }}</strong>
            </div>
            <div class="cache-item">
              <span>LLM 请求数</span>
              <strong>{{ cacheStats.llm.hits + cacheStats.llm.misses }}</strong>
            </div>
            <div class="cache-item">
              <span>估算 Token 节省</span>
              <strong>{{ cacheStats.llm.estimated_tokens_saved?.toLocaleString() || 0 }}</strong>
            </div>
            <div class="cache-item">
              <span>估算成本节省</span>
              <strong>${{ ((cacheStats.llm.estimated_tokens_saved || 0) / 1000 * 0.002).toFixed(4) }}</strong>
            </div>
          </div>
          <button class="btn-secondary mt-2" @click="clearCache">清空缓存</button>
        </div>
      </div>
    </div>

    <div v-if="tab === 'backup'" class="tab-content">
      <button class="btn-primary" @click="doBackup">立即备份</button>
      <p class="mt-2 hint">备份数据存储在 data/chroma_backup/ 目录</p>
    </div>

    <div v-if="tab === 'config'" class="tab-content">
      <p class="hint">运行配置可通过后端 config.py 或环境变量调整。前端当前连接 API: /api</p>
    </div>
  </div>
</template>

<style scoped>
.system-page { max-width: 900px; }
.tabs { display: flex; gap: 0; margin-bottom: 24px; border-bottom: 1px solid var(--color-hairline); }
.tabs button {
  padding: 10px 20px; background: none; border: none; font-size: 14px; font-weight: 500;
  color: var(--color-mute); cursor: pointer; border-bottom: 2px solid transparent;
}
.tabs button:hover { color: var(--color-ink); }
.tabs button.active { color: var(--color-ink); border-bottom-color: var(--color-ink); }
.stat-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
.stat-card {
  background: var(--color-canvas); border-radius: var(--radius-lg); padding: 24px;
  box-shadow: var(--shadow-card);
}
.stat-card h3 { margin: 0 0 12px; font-size: 16px; }
.metric-big { font-size: 36px; font-weight: 600; color: var(--color-ink); }
.metric-sub { font-size: 14px; color: var(--color-mute); margin-bottom: 12px; }
.json-dump { font-size: 11px; padding: 12px; background: var(--color-canvas-soft-2); border-radius: var(--radius-sm); overflow-x: auto; }
.cache-metrics { display: flex; flex-direction: column; gap: 8px; }
.cache-item { display: flex; justify-content: space-between; font-size: 14px; padding: 4px 0; border-bottom: 1px solid var(--color-hairline); }
.cache-item span { color: var(--color-mute); }
.cache-item strong { color: var(--color-ink); }
.mt-2 { margin-top: 12px; }
.hint { font-size: 14px; color: var(--color-mute); }
@media (max-width: 768px) { .stat-grid { grid-template-columns: 1fr; } }
</style>
