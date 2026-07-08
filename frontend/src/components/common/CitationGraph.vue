<script setup lang="ts">
import { computed } from 'vue'
import type { CitationEntry } from '@/api/types'

const props = defineProps<{
  cites: CitationEntry[]
  citedBy: CitationEntry[]
  centerLabel: string
}>()

interface GraphNode {
  id: string
  label: string
  x: number
  y: number
  isCenter: boolean
  inDb: boolean
}

const nodes = computed<GraphNode[]>(() => {
  const result: GraphNode[] = []
  // Center node
  result.push({
    id: 'center',
    label: props.centerLabel,
    x: 50, y: 50,
    isCenter: true,
    inDb: true,
  })

  // Cites (outgoing) — left side
  const citeCount = props.cites.length
  props.cites.forEach((c, i) => {
    const angle = (i / Math.max(citeCount, 1)) * Math.PI - Math.PI / 2
    const radius = 32
    const x = 50 - Math.cos(angle) * radius
    const y = 50 + Math.sin(angle) * radius
    result.push({
      id: c.cited_arxiv_id || `cite-${i}`,
      label: (c.cited_title || c.cited_arxiv_id || `?`).slice(0, 30),
      x, y,
      isCenter: false,
      inDb: c.in_db,
    })
  })

  // Cited by (incoming) — right side
  const byCount = props.citedBy.length
  props.citedBy.forEach((c, i) => {
    const angle = (i / Math.max(byCount, 1)) * Math.PI - Math.PI / 2
    const radius = 32
    const x = 50 + Math.cos(angle) * radius
    const y = 50 + Math.sin(angle) * radius
    result.push({
      id: c.citing_arxiv_id || `citedby-${i}`,
      label: (c.citing_title || c.citing_arxiv_id || `?`).slice(0, 30),
      x, y,
      isCenter: false,
      inDb: c.in_db,
    })
  })

  return result
})

const edges = computed(() => {
  const result: { from: string; to: string }[] = []
  props.cites.forEach((c, i) => {
    result.push({ from: 'center', to: c.cited_arxiv_id || `cite-${i}` })
  })
  props.citedBy.forEach((c, i) => {
    result.push({ from: c.citing_arxiv_id || `citedby-${i}`, to: 'center' })
  })
  return result
})
</script>

<template>
  <div class="citation-graph">
    <div v-if="!cites.length && !citedBy.length" class="graph-empty">
      暂无引用关系数据
    </div>
    <svg v-else viewBox="0 0 100 100" class="graph-svg">
      <!-- Edges -->
      <line
        v-for="(e, i) in edges" :key="'e'+i"
        :x1="nodes.find(n=>n.id===e.from)?.x || 50"
        :y1="nodes.find(n=>n.id===e.from)?.y || 50"
        :x2="nodes.find(n=>n.id===e.to)?.x || 50"
        :y2="nodes.find(n=>n.id===e.to)?.y || 50"
        class="graph-edge"
        :class="{ outgoing: e.from === 'center', incoming: e.to === 'center' }"
      />
      <!-- Nodes -->
      <g v-for="n in nodes" :key="n.id">
        <circle
          :cx="n.x" :cy="n.y" :r="n.isCenter ? 5 : 3"
          :class="['graph-node', {
            center: n.isCenter,
            'in-db': n.inDb && !n.isCenter,
            'not-in-db': !n.inDb && !n.isCenter,
          }]"
        />
        <text
          :x="n.x" :y="n.y + (n.isCenter ? 8 : 5)"
          :class="['graph-label', { 'label-center': n.isCenter }]"
          text-anchor="middle"
        >{{ n.isCenter ? n.label.slice(0, 12) : n.label.slice(0, 8) }}</text>
      </g>
    </svg>
    <div class="graph-legend">
      <span class="legend-item"><span class="dot outgoing"></span> 引用了</span>
      <span class="legend-item"><span class="dot incoming"></span> 被引用</span>
      <span class="legend-item"><span class="dot in-db"></span> 已在库中</span>
    </div>
  </div>
</template>

<style scoped>
.citation-graph {
  background: var(--color-canvas);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
  padding: 24px;
  margin-bottom: 20px;
}
.graph-empty { text-align: center; color: var(--color-mute); padding: 32px; font-size: 14px; }
.graph-svg {
  width: 100%;
  max-height: 350px;
}
.graph-edge {
  stroke: var(--color-hairline);
  stroke-width: 0.5;
}
.graph-edge.outgoing { stroke: #0070f3; stroke-dasharray: 2,1; }
.graph-edge.incoming { stroke: #059669; stroke-dasharray: 2,1; }
.graph-node { fill: var(--color-mute); }
.graph-node.center { fill: var(--color-ink); }
.graph-node.in-db { fill: #0070f3; }
.graph-node.not-in-db { fill: var(--color-hairline-strong); }
.graph-label { font-size: 2.5px; fill: var(--color-mute); }
.graph-label.label-center { font-weight: 600; fill: var(--color-ink); }
.graph-legend {
  display: flex; gap: 16px; justify-content: center;
  margin-top: 12px; font-size: 12px; color: var(--color-mute);
}
.legend-item { display: flex; align-items: center; gap: 4px; }
.dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.dot.center { background: var(--color-ink); }
.dot.outgoing { background: #0070f3; }
.dot.incoming { background: #059669; }
.dot.in-db { background: #0070f3; }
</style>
