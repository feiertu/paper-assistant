<script setup lang="ts">
import { ref, nextTick, computed } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { agentApi } from '@/api/client'
import { streamAgentSSE } from '@/composables/useStreaming'
import ChatBubble from '@/components/common/ChatBubble.vue'
import ThinkingIndicator from '@/components/common/ThinkingIndicator.vue'

interface Step {
  type: 'thinking' | 'tool_call' | 'tool_result' | 'error'
  tool?: string
  content?: string
  result?: string
  timestamp: number
}

const auth = useAuthStore()
const query = ref('')
const lang = ref<'zh' | 'en'>('zh')
const maxIter = ref(10)
const temperature = ref(0.1)
const loading = ref(false)
const answer = ref('')
const steps = ref<Step[]>([])
const usage = ref('')
const error = ref('')
const currentThinking = ref('')

function toolIcon(tool: string): string {
  const map: Record<string, string> = {
    search_papers: '[S]', retrieve: '[R]', summarize: '[Sm]',
    compare: '[C]', citations: '[Ct]', survey: '[Sv]',
  }
  return map[tool] || '[*]'
}

function toolLabel(tool: string): string {
  const map: Record<string, string> = {
    search_papers: '搜索论文', retrieve: '检索内容', summarize: '生成摘要',
    compare: '对比分析', citations: '查询引用', survey: '综述生成',
  }
  return map[tool] || tool
}

const stepCount = computed(() => steps.value.filter(s => s.type === 'tool_call').length)

async function runAgent() {
  if (!query.value.trim()) return
  loading.value = true
  error.value = ''
  answer.value = ''
  steps.value = []
  usage.value = ''
  currentThinking.value = ''

  try {
    const resp = await agentApi.queryStream(auth.ownerId, query.value, lang.value, maxIter.value, temperature.value)
    for await (const event of streamAgentSSE(resp)) {
      const ts = Date.now()
      if (event.type === 'answer_chunk') {
        answer.value += (event.content as string) || ''
        await nextTick()
      } else if (event.type === 'thinking') {
        currentThinking.value = (event.content as string) || ''
      } else if (event.type === 'tool_call') {
        steps.value.push({
          type: 'tool_call',
          tool: event.tool as string,
          timestamp: ts,
        })
        currentThinking.value = ''
      } else if (event.type === 'tool_result') {
        const resultStr = (event.result as string) || ''
        steps.value.push({
          type: 'tool_result',
          tool: event.tool as string,
          result: resultStr.length > 300 ? resultStr.slice(0, 300) + '…' : resultStr,
          timestamp: ts,
        })
      } else if (event.type === 'error') {
        steps.value.push({
          type: 'error',
          tool: event.tool as string,
          content: event.message as string,
          timestamp: ts,
        })
      } else if (event.type === 'usage') {
        usage.value = `${(event.total_tokens as number)?.toLocaleString()} tokens · ${event.steps} 步 · ${event.duration_ms}ms`
      }
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Agent 执行失败'
  } finally {
    loading.value = false
    currentThinking.value = ''
  }
}
</script>

<template>
  <div class="agent-page">
    <div class="agent-header">
      <h2>智能分析</h2>
      <p class="page-desc">AI Agent 自主调用搜索、摘要、对比、引用等工具，多步推理处理复杂研究问题。</p>
    </div>

    <div class="qa-input-area">
      <textarea
        v-model="query" class="form-input" style="height:80px; resize:none"
        placeholder="例如：找出 VLM 在机器人操作中的最新论文，总结技术路线并推荐研究方向"
      ></textarea>
      <div class="controls-row">
        <div class="control-group">
          <label>语言</label>
          <select v-model="lang" class="form-input" style="width:auto">
            <option value="zh">中文</option>
            <option value="en">English</option>
          </select>
        </div>
        <div class="control-group">
          <label>步数 {{ maxIter }}</label>
          <input v-model.number="maxIter" type="range" min="1" max="20" />
        </div>
        <div class="control-group">
          <label>温度 {{ temperature }}</label>
          <input v-model.number="temperature" type="range" min="0" max="1.5" step="0.1" />
        </div>
        <button class="btn-primary" :disabled="!query.trim() || loading" @click="runAgent">
          {{ loading ? '推理中…' : '开始推理' }}
        </button>
      </div>
    </div>

    <div v-if="error" class="error-msg">{{ error }}</div>

    <!-- Agent workspace: steps sidebar + answer main -->
    <div v-if="loading || answer || steps.length" class="agent-workspace">
      <!-- Steps sidebar -->
      <div class="steps-panel">
        <div class="steps-header">
          推理过程
          <span v-if="stepCount" class="steps-badge">{{ stepCount }} 步</span>
        </div>
        <div class="steps-body">
          <div v-if="loading && currentThinking" class="step-item thinking">
            <div class="step-icon">...</div>
            <div class="step-text">{{ currentThinking }}</div>
          </div>
          <div v-for="(s, i) in steps" :key="i" :class="['step-item', s.type]">
            <template v-if="s.type === 'tool_call'">
              <div class="step-icon">{{ toolIcon(s.tool || '') }}</div>
              <div class="step-text">
                <div class="step-tool-name">{{ toolLabel(s.tool || '') }}</div>
              </div>
            </template>
            <template v-else-if="s.type === 'tool_result'">
              <div class="step-result-text">{{ s.result }}</div>
            </template>
            <template v-else-if="s.type === 'error'">
              <div class="step-icon">!</div>
              <div class="step-text error-text">{{ s.tool }}: {{ s.content }}</div>
            </template>
          </div>
        </div>
        <div v-if="usage" class="steps-footer">{{ usage }}</div>
      </div>

      <!-- Answer -->
      <div class="answer-panel">
        <ThinkingIndicator v-if="loading && !answer" text="Agent 正在分析…" />
        <div v-if="answer" class="answer-content">
          <h3>分析结果</h3>
          <ChatBubble :content="answer" role="assistant" :is-markdown="true" />
        </div>
      </div>
    </div>

    <div v-if="!answer && !loading" class="empty-hint">
      <h3>试试这些问题</h3>
      <ul>
        <li>"梳理 VLM 在机器人操作中的技术路线"</li>
        <li>"对比论文 X 和论文 Y 的方法差异"</li>
        <li>"分析已入库论文的研究趋势"</li>
        <li>"找出与 spatial reasoning 相关的所有论文并总结"</li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.agent-page { max-width: 1100px; }
.agent-header { margin-bottom: 16px; }
.agent-header h2 { margin-bottom: 4px; }
.page-desc { font-size: 14px; color: var(--color-body); margin: 0; }
.qa-input-area {
  background: var(--color-canvas); border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card); padding: 24px; margin-bottom: 20px;
}
.controls-row { display: flex; align-items: flex-end; gap: 16px; margin-top: 16px; flex-wrap: wrap; }
.control-group { display: flex; flex-direction: column; gap: 4px; }
.control-group label { font-size: 12px; color: var(--color-mute); font-weight: 500; }

/* Workspace layout */
.agent-workspace {
  display: grid; grid-template-columns: 320px 1fr; gap: 20px;
  min-height: 400px;
}
.steps-panel {
  background: var(--color-canvas); border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card); display: flex; flex-direction: column;
  max-height: 500px; overflow: hidden;
}
.steps-header {
  padding: 14px 16px; font-size: 14px; font-weight: 600; color: var(--color-ink);
  border-bottom: 1px solid var(--color-hairline);
  display: flex; align-items: center; gap: 8px;
}
.steps-badge { font-size: 11px; background: var(--color-canvas-soft-2); color: var(--color-mute); padding: 2px 8px; border-radius: var(--radius-full); }
.steps-body { flex: 1; overflow-y: auto; padding: 8px 12px; }
.steps-footer { padding: 10px 16px; border-top: 1px solid var(--color-hairline); font-size: 11px; color: var(--color-mute); text-align: right; }
.step-item { display: flex; gap: 8px; padding: 8px 0; border-bottom: 1px solid var(--color-hairline); }
.step-item:last-child { border-bottom: none; }
.step-icon { font-size: 16px; flex-shrink: 0; width: 22px; text-align: center; }
.step-text { flex: 1; min-width: 0; }
.step-tool-name { font-size: 13px; font-weight: 600; color: var(--color-ink); }
.step-result-text { font-size: 12px; color: var(--color-mute); line-height: 1.5; overflow: hidden; text-overflow: ellipsis; white-space: pre-wrap; }
.thinking .step-text { font-size: 13px; color: var(--color-mute); font-style: italic; }
.error-text { font-size: 12px; color: var(--color-error); }

.answer-panel {
  background: var(--color-canvas); border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card); padding: 24px; min-height: 200px;
}
.answer-content h3 { margin: 0 0 12px; }

.error-msg { padding: 12px; background: var(--color-error-soft); color: var(--color-error-deep); border-radius: var(--radius-sm); margin-bottom: 16px; }
.empty-hint { padding: 48px 0; text-align: center; color: var(--color-mute); }
.empty-hint h3 { font-size: 16px; color: var(--color-mute); margin-bottom: 12px; }
.empty-hint ul { list-style: none; padding: 0; max-width: 500px; margin: 0 auto; }
.empty-hint li { padding: 6px 0; font-size: 14px; }

@media (max-width: 768px) {
  .agent-workspace { grid-template-columns: 1fr; }
}
</style>
