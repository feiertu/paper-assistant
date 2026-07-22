# 论文抓取中心 — 功能设计

> 创建日期：2026-07-22  
> 状态：待评审  
> 关联：LibraryPage 去重透明性 + 抓取历史持久化

## 背景与动机

当前论文抓取功能存在以下问题：

1. **抓取 UI 隐藏过深**：[LibraryPage.vue](../frontend/src/components/pages/LibraryPage.vue) 中 arXiv 抓取表单放在 `<details>` 折叠面板内，入口不明显。
2. **去重不透明**：arXiv API 返回的论文中，已入库的会被 `get_existing_ids()` 静默跳过，用户看不到被跳过了哪些论文。
3. **抓取结果不持久化**：pipeline 各步骤的结果仅通过 toast 通知短暂显示，关闭后无法回溯。
4. **职责不清晰**：LibraryPage 同时承担论文浏览、搜索、筛选、收藏管理和 arXiv 抓取，功能堆叠。

## 设计目标

1. 新建独立的「论文抓取」页面，将抓取表单从 LibraryPage 移出
2. 每次抓取结束后清晰展示：找到、成功入库、因去重跳过、失败的论文数
3. 列出被跳过论文的 arxiv_id 和标题
4. 抓取历史持久化到数据库，支持回溯查看
5. LibraryPage 回归纯粹的论文浏览/搜索/管理职责

## 整体架构

```
新页面: /fetch → FetchPage.vue
  ├─ 抓取表单区域
  ├─ 本次抓取结果区域（实时 + 摘要）
  └─ 历史记录区域（列表 + 分页）

改造: /library → LibraryPage.vue
  ├─ 移除 <details> arXiv 抓取面板
  ├─ 保留 pending 黄色提示条
  └─ 保留状态筛选（全部/已入库/待处理/失败）
```

### 侧边栏导航

[Sidebar.vue](../frontend/src/components/layout/Sidebar.vue) 新增导航项：

| key | label | icon |
|-----|-------|------|
| `fetch` | 论文抓取 | — |

### 路由

[router/index.ts](../frontend/src/router/index.ts) 新增：

```typescript
{
  path: '/fetch',
  name: 'fetch',
  component: () => import('@/components/pages/FetchPage.vue'),
  meta: { title: '论文抓取' },
}
```

## 数据模型

### 新表：`fetch_history`

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK AUTOINCREMENT | 自增主键 |
| `query_text` | TEXT NOT NULL | arXiv 搜索查询语法 |
| `max_results` | INTEGER NOT NULL | 请求返回篇数 |
| `total_found` | INTEGER DEFAULT 0 | arXiv API 实际返回的论文总数 |
| `fetched` | INTEGER DEFAULT 0 | 成功保存元数据（新论文）的数量 |
| `skipped` | INTEGER DEFAULT 0 | 因已入库跳过的数量 |
| `download_success` | INTEGER DEFAULT 0 | PDF 下载成功数 |
| `download_failed` | INTEGER DEFAULT 0 | PDF 下载失败数 |
| `parse_success` | INTEGER DEFAULT 0 | PDF 解析成功数 |
| `parse_failed` | INTEGER DEFAULT 0 | PDF 解析失败数 |
| `ingested` | INTEGER DEFAULT 0 | 最终入库数 |
| `skipped_papers` | TEXT DEFAULT '[]' | 跳过的论文列表（JSON），格式 `[{"id":"...","title":"..."}, ...]` |
| `owner_id` | TEXT NOT NULL DEFAULT '' | 用户隔离 |
| `created_at` | TEXT NOT NULL | 抓取时间（ISO 格式） |

### 设计决策

- **跳过论文信息存储方式**：`skipped_papers` 存 JSON 数组（id + title），避免关联查询。体积小（每篇 ~150 字节），不涉及复杂 JOIN。
- **不用外键**：与现有 `papers` 表风格一致（SQLite + 手动管理一致性）。
- **owner_id 隔离**：与现有 PaperDAO 一致。

### 现有端点改造

**`POST /arxiv/pipeline`** — 执行结束后写入 `fetch_history` 表。跳过论文信息从 `fetch_and_persist()` 获取（该函数目前只返回 `new_papers`，需改造为同时返回跳过的论文列表）。

## API 接口

### 新增接口

#### `GET /fetch/history`

查询抓取历史（按 owner 隔离）。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `limit` | int | 20 | 每页条数（1-100） |
| `offset` | int | 0 | 偏移量 |

返回：

```json
{
  "records": [
    {
      "id": 1,
      "query_text": "cat:cs.AI",
      "max_results": 5,
      "total_found": 5,
      "fetched": 3,
      "skipped": 2,
      "download_success": 3,
      "download_failed": 0,
      "parse_success": 3,
      "parse_failed": 0,
      "ingested": 3,
      "skipped_papers": [{"id": "2001.01234", "title": "Attention Is All You Need"}],
      "created_at": "2026-07-22T14:30:00"
    }
  ],
  "total": 10
}
```

#### `GET /fetch/history/{id}`

单次抓取详情（含跳过的论文列表）。

返回结构与列表项相同，增加错误详情（如果 pipeline 返回了 download/parse errors）。

### 改造现有接口

#### `POST /arxiv/pipeline`

返回值不变，但执行后自动写入 `fetch_history` 表。同时改造 `fetch_and_persist()` 函数使其返回跳过的论文信息。

#### `POST /arxiv/process-pending`

同样写入 `fetch_history`（query_text 记为 `"<手动处理待入库>"`）。

## 前端设计

### 文件结构

```
frontend/src/
├── components/
│   └── pages/
│       └── FetchPage.vue          ← 新建
├── router/index.ts                ← 改造：新增 /fetch 路由
├── components/layout/Sidebar.vue  ← 改造：新增导航项
├── api/client.ts                  ← 改造：新增 fetchApi
└── api/types.ts                   ← 改造：新增类型
```

### FetchPage.vue 布局

```
┌─ 论文抓取 ───────────────────────────────────────────┐
│  从 arXiv 搜索并抓取论文，查看抓取历史。                 │
│                                                     │
│  ┌─ 📥 抓取论文 ─────────────────────────────────┐  │
│  │  查询语法  [cat:cs.AI AND ti:learning  ]         │  │
│  │  最大篇数  [5 ▼]  (1-50)                       │  │
│  │  [ 一键抓取 ]  (loading: "抓取中…")              │  │
│  └───────────────────────────────────────────────┘  │
│                                                     │
│  ┌─ 📊 本次抓取结果 (抓取完成后显示) ──────────────┐  │
│  │  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐         │  │
│  │  │找到 5│ │成功 3│ │跳过 2│ │失败 0│         │  │
│  │  └──────┘ └──────┘ └──────┘ └──────┘         │  │
│  │                                               │  │
│  │  ▶ 跳过论文（因已入库）                          │  │
│  │    2001.01234 · Attention Is All You Need      │  │
│  │    1905.08765 · BERT: Pre-training of ...      │  │
│  └───────────────────────────────────────────────┘  │
│                                                     │
│  ┌─ 📜 抓取历史 ─────────────────────────────────┐  │
│  │  ┌──────┬──────┬─────┬────┬────┬────┬────┐   │  │
│  │  │ 时间  │ 查询  │最大 │找到│成功│跳过│失败│   │  │
│  │  ├──────┼──────┼─────┼────┼────┼────┼────┤   │  │
│  │  │07/22 │cat:cs│  5  │ 5  │ 3  │ 2  │ 0  │   │  │
│  │  └──────┴──────┴─────┴────┴────┴────┴────┘   │  │
│  │                                               │  │
│  │              [分页控件]                         │  │
│  └───────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

### 状态管理

页面内使用 Vue ref 管理，不需要 Pinia store：

| 变量 | 类型 | 说明 |
|------|------|------|
| `fetchQuery` | `string` | arXiv 查询语法 |
| `fetchN` | `number` | 最大篇数 |
| `fetching` | `boolean` | 抓取进行中 |
| `lastResult` | `FetchResult \| null` | 本次抓取结果 |
| `history` | `FetchRecord[]` | 历史记录列表 |
| `historyTotal` | `number` | 历史记录总数 |
| `historyPage` | `number` | 历史记录页码 |
| `loadingHistory` | `boolean` | 历史记录加载中 |

### 交互细节

1. **抓取过程**：点击"一键抓取" → 按钮变灰 + 文字变"抓取中…" → 完成后展示结果区域
2. **结果步骤展示**：复用 pipeline 返回的 `steps` 数组，逐条显示每步进度
3. **跳过论文列表**：默认展开，每行显示 `arxiv_id` + 标题
4. **历史记录**：翻页加载，点击某行可展开查看当次完整结果（复用 `lastResult` 区域样式）
5. **空状态**：暂无抓取历史时使用 `EmptyState` 组件

### 组件复用

| 组件 | 用途 |
|------|------|
| `EmptyState` | 暂无历史记录 |
| `Pagination` | 历史记录分页 |
| `statusBar` 样式 | 结果统计卡片（找到/成功/跳过/失败） |

### LibraryPage 变更

1. **移除**：`<details>` arXiv 抓取面板及其相关变量（`fetchQuery`, `fetchN`, `fetching`, `doFetch`）
2. **保留**：
   - `pendingCount` + `processPending` + 黄色 pending 提示条（待处理论文管理）
   - `doIngest` 按钮（重新入库）
   - 状态筛选（全部/已入库/待处理/失败）
   - import：移除 `arxivApi`
3. **可选**：在 actions-bar 增加一个指向 `/fetch` 的快捷链接按钮

## 涉及文件清单

### 新建

| 文件 | 说明 |
|------|------|
| `frontend/src/components/pages/FetchPage.vue` | 抓取中心页面 |
| `migrations/versions/002_fetch_history.py` | 新建 fetch_history 表的 DDL 迁移 |

### 修改

| 文件 | 变更内容 |
|------|----------|
| `src/api/main.py` | pipeline/process-pending 写入 fetch_history；新增 GET `/fetch/history`、`/fetch/history/{id}` |
| `src/fetch/arxiv.py` | `fetch_and_persist()` 返回跳过的论文列表 |
| `src/db/schema.py` | 新增 FetchHistory dataclass + DDL |
| `src/db/dao.py` | 新增 FetchHistoryDAO |
| `frontend/src/router/index.ts` | 新增 `/fetch` 路由 |
| `frontend/src/components/layout/Sidebar.vue` | 新增「论文抓取」导航项 |
| `frontend/src/api/client.ts` | 新增 `fetchApi` + `POST /arxiv/pipeline` 返回类型扩展 |
| `frontend/src/api/types.ts` | 新增 `FetchRecord`、`FetchResult` 等类型 |
| `frontend/src/components/pages/LibraryPage.vue` | 移除 arXiv 抓取 UI，保留 pending 条 |

## 验收标准

1. 侧边栏出现「论文抓取」入口，点击进入 `/fetch` 页面
2. 在抓取中心发起 arXiv 抓取，完成后显示：找到 N / 成功 N / 跳过 N / 失败 N
3. 跳过论文区域列出 arxiv_id + 标题
4. 历史记录列表显示过往抓取摘要，支持分页
5. 刷新页面后历史记录仍存在
6. LibraryPage 移除 arXiv 抓取面板，pending 处理功能保持不变
7. 现有 `/arxiv/pipeline` API 返回值不变（向后兼容）
