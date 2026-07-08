<script setup lang="ts">
const faqItems = [
  {
    q: '论文是怎么从 arXiv 到你眼前的？',
    a: `每篇论文要经过 **4 个步骤** 才能用来提问：

| 步骤 | 做什么 | 成功标志 |
|------|--------|----------|
| 1. 搜索 | 从 arXiv 找到论文标题、作者、摘要 | 论文出现在列表中 |
| 2. 下载 | 下载 PDF 到 data/raw/ | 文件存在 |
| 3. 解析 | 把 PDF 转成结构化的 JSON | 生成 data/parsed/*.json |
| 4. 入库 | 切成小片段，转成向量，存进 ChromaDB | chunk 数 > 0 |

如果显示 "0块"，说明论文卡在第 2、3 或 4 步。点「论文库」页面的 "处理" 按钮重试。`,
  },
  {
    q: '智能问答 vs 智能分析 — 何时用哪个？',
    a: `| | 智能问答 | 智能分析 (Agent) |
|--|---------|-----------------|
| 怎么工作 | 向量检索 -> 一次性回答 | AI 自主调用工具，分步执行 |
| 全局分析 | [Y] 支持（勾选"全局分析模式"） | [N] 不适合（步数限制） |
| 具体问题 | [Y] 最佳选择 | [Y] 也可以 |
| 综合研究 | [!] 受检索片段限制 | [Y] 最佳选择 |
| 速度 | 快（1次 LLM 调用） | 慢（5-20 次 LLM 调用） |
| Token 消耗 | 低 | 高 |`,
  },
  {
    q: 'arXiv 搜索语法说明',
    a: `| 语法 | 含义 | 例 |
|------|------|-----|
| cat:cs.AI | 限定分类 | cat:cs.CL 只搜计算语言学 |
| ti:关键词 | 搜标题 | ti:transformer 标题含 transformer |
| au:作者 | 搜作者 | au:bengio Yoshua Bengio 的论文 |
| abs:关键词 | 搜摘要 | abs:reinforcement learning |
| AND / OR | 组合条件 | cat:cs.AI AND ti:robot |`,
  },
  {
    q: '温度 (Temperature) 是什么？',
    a: `温度控制 AI 回答的**随机性**：
- **0 ~ 0.3（低）**：回答稳定、严谨。适合需要准确答案的场合
- **0.3 ~ 0.7（中）**：平衡创造性和准确性。适合一般问答
- **0.7 ~ 1.5（高）**：回答多变、有创造性、也可能跑偏。适合头脑风暴

默认值是 0.3（问答）和 0.1（智能分析）。`,
  },
  {
    q: '缓存机制与 Token 节省',
    a: `**两层缓存：**
| 缓存层 | TTL | 容量 | 命中条件 |
|--------|-----|------|----------|
| LLM 缓存 | 30 分钟 | 200 条 | 相同的 query + context + lang + task |
| Embedding 缓存 | 24 小时 | 2000 条 | 相同的文本 + provider |

同一篇论文反复生成摘要时，基于论文 ID + 全文哈希做缓存 key，确保 100% 命中。`,
  },
  {
    q: '论文语言问题的说明',
    a: '抓到的论文是原文，没有翻译过。系统的"语言"选项控制的是 **AI 用哪种语言回答你**，不是翻译论文内容。如果你看到中文标题/摘要，那是原作者自己写的中文。',
  },
]
</script>

<template>
  <div class="help-page">
    <h2>帮助</h2>

    <details v-for="(item, i) in faqItems" :key="i" :open="i === 0" class="faq-item">
      <summary>{{ item.q }}</summary>
      <div class="faq-content" v-html="item.a.replace(/\n/g, '<br>')"></div>
    </details>

    <div class="faq-item" style="margin-top:24px">
      <h3>各页面功能速览</h3>
      <table>
        <thead><tr><th>页面</th><th>一句话说明</th></tr></thead>
        <tbody>
          <tr><td>智能问答</td><td>对已有论文提问（支持全局分析模式分析全部论文主旨）</td></tr>
          <tr><td>智能分析</td><td>AI 自主使用多种工具完成复杂研究任务</td></tr>
          <tr><td>论文库</td><td>搜索 arXiv、管理论文、点击标题浏览分块/原文</td></tr>
          <tr><td>摘要 & 综述</td><td>生成单篇摘要、多篇综述、找相似论文</td></tr>
          <tr><td>引用关系</td><td>查看论文之间的引用网络</td></tr>
          <tr><td>数据管理</td><td>入库、导出、备份数据</td></tr>
          <tr><td>系统设置</td><td>查看状态、清缓存、备份恢复、成本估算</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.help-page { max-width: 800px; }
.faq-item {
  background: var(--color-canvas);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-card);
  margin-bottom: 12px;
  padding: 16px 24px;
}
.faq-item summary {
  font-size: 15px;
  font-weight: 600;
  color: var(--color-ink);
  cursor: pointer;
  padding: 4px 0;
}
.faq-content {
  padding-top: 12px;
  font-size: 14px;
  line-height: 1.7;
  color: var(--color-body);
}
.faq-content table {
  width: 100%;
  border-collapse: collapse;
  margin: 12px 0;
}
.faq-content th, .faq-content td {
  padding: 8px 12px;
  text-align: left;
  border-bottom: 1px solid var(--color-hairline);
  font-size: 13px;
}
.faq-content th {
  background: var(--color-canvas-soft);
  font-weight: 600;
  color: var(--color-ink);
}
.faq-item h3 {
  font-size: 18px;
  margin: 0 0 12px;
}
.faq-item table {
  width: 100%;
  border-collapse: collapse;
}
.faq-item th, .faq-item td {
  padding: 8px 12px;
  text-align: left;
  border-bottom: 1px solid var(--color-hairline);
  font-size: 13px;
}
.faq-item th {
  background: var(--color-canvas-soft);
  font-weight: 600;
  color: var(--color-ink);
}
</style>
