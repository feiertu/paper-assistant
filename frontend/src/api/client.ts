/**
 * HTTP API Client — communicates with FastAPI backend.
 * All UI operations go through this module, never import backend directly.
 */

const API_BASE = '/api'

function headers(ownerId: string): Record<string, string> {
  const h: Record<string, string> = { 'X-Owner-Id': ownerId }
  return h
}

async function get(path: string, ownerId: string, params?: Record<string, string | number>): Promise<Response> {
  const url = new URL(`${API_BASE}${path}`, window.location.origin)
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== '' && v !== undefined && v !== null) url.searchParams.set(k, String(v))
    })
  }
  return safeFetch(url.toString(), { headers: headers(ownerId) })
}

async function post(path: string, ownerId: string, body?: unknown, timeout = 120_000): Promise<Response> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeout)
  try {
    return await safeFetch(`${API_BASE}${path}`, {
      method: 'POST',
      headers: { ...headers(ownerId), 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : '{}',
      signal: controller.signal,
    })
  } finally {
    clearTimeout(timer)
  }
}

async function del(path: string, ownerId: string): Promise<Response> {
  return safeFetch(`${API_BASE}${path}`, { method: 'DELETE', headers: headers(ownerId) })
}

/** Helper: parse JSON response safely */
async function json<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    const text = await resp.text().catch(() => '')
    throw new Error(`API error ${resp.status}: ${text}`)
  }
  return resp.json()
}

/** Helper: wrap fetch with better error messages */
async function safeFetch(url: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(url, init)
  } catch (e) {
    if (e instanceof TypeError && e.message === 'Failed to fetch') {
      throw new Error('无法连接到后端服务，请检查服务是否启动')
    }
    throw e
  }
}

// ══════════════════════════════════════════════════════════════
//  Papers
// ══════════════════════════════════════════════════════════════

export const papersApi = {
  list: (ownerId: string, limit = 50, offset = 0) =>
    get('/papers', ownerId, { limit, offset }).then(r => json<import('./types').PaperListResponse>(r)),

  get: (ownerId: string, arxivId: string) =>
    get(`/papers/${arxivId}`, ownerId).then(r => json<import('./types').Paper>(r)),

  search: (ownerId: string, params: Record<string, string | number>) =>
    get('/papers/search', ownerId, params).then(r => json<import('./types').PaperListResponse>(r)),

  chunks: (ownerId: string, arxivId: string, limit = 500) =>
    get(`/papers/${arxivId}/chunks`, ownerId, { limit }).then(r => json<import('./types').ChunkListResponse>(r)),

  pdfUrl: (_ownerId: string, arxivId: string) =>
    `${API_BASE}/papers/${arxivId}/pdf`,

  recommend: (ownerId: string, arxivId: string, topK = 5) =>
    post('/papers/recommend', ownerId, { arxiv_id: arxivId, top_k: topK }).then(r => json<import('./types').RecommendResponse>(r)),

  analyze: (ownerId: string, query: string, lang = 'zh') =>
    post('/papers/analyze', ownerId, { query, lang }).then(r => json<import('./types').AnalyzeResponse>(r)),

  citations: (ownerId: string, arxivId: string) =>
    get(`/papers/${arxivId}/citations`, ownerId).then(r => json<import('./types').CitationGraph>(r)),
}

// ══════════════════════════════════════════════════════════════
//  RAG
// ══════════════════════════════════════════════════════════════

export const ragApi = {
  retrieve: (ownerId: string, query: string, topK = 5) =>
    post('/retrieve', ownerId, { query, top_k: topK }).then(r => json<import('./types').RetrieveResponse>(r)),

  query: (ownerId: string, query: string, topK = 5, lang = 'zh') =>
    post('/rag/query', ownerId, { query, top_k: topK, lang }).then(r => json<import('./types').RagQueryResponse>(r)),

  /** SSE streaming RAG query — returns a ReadableStream of token strings */
  queryStream: (ownerId: string, query: string, topK = 5, lang = 'zh', temperature?: number) =>
    post('/rag/query/stream', ownerId, {
      query, top_k: topK, lang,
      ...(temperature !== undefined ? { temperature } : {}),
    }),
}

// ══════════════════════════════════════════════════════════════
//  Agent
// ══════════════════════════════════════════════════════════════

export const agentApi = {
  /** SSE streaming Agent query */
  queryStream: (ownerId: string, query: string, lang = 'zh', maxIterations = 10, temperature = 0.1) =>
    post('/agent/query/stream', ownerId, {
      query, lang, max_iterations: maxIterations, temperature,
    }, 600_000),
}

// ══════════════════════════════════════════════════════════════
//  Store / Ingest
// ══════════════════════════════════════════════════════════════

export const storeApi = {
  stats: (ownerId: string) =>
    get('/store/stats', ownerId).then(r => json<import('./types').StoreStats>(r)),

  papers: (ownerId: string) =>
    get('/store/papers', ownerId).then(r => json<{ arxiv_id: string; title: string }[]>(r)),

  reset: (ownerId: string) =>
    del('/store/reset', ownerId).then(r => json<unknown>(r)),

  ingest: (ownerId: string, reset = false, parsedDir = '') =>
    post('/ingest', ownerId, { reset, parsed_dir: parsedDir }, 300_000).then(r => json<import('./types').IngestResult>(r)),

  backup: (ownerId: string) =>
    post('/store/backup', ownerId).then(r => json<{ backup_name: string; status?: string }>(r)),

  restore: (ownerId: string, backupName: string) =>
    post('/store/restore', ownerId, { backup_name: backupName }).then(r => json<unknown>(r)),
}

// ══════════════════════════════════════════════════════════════
//  arXiv Pipeline
// ══════════════════════════════════════════════════════════════

export const arxivApi = {
  pipeline: (ownerId: string, query: string, maxResults = 5) =>
    post('/arxiv/pipeline', ownerId, {
      query, max_results: maxResults, auto_ingest: true,
    }, 1_800_000).then(r => json<import('./types').ArxivPipelineResponse>(r)),

  fetch: (ownerId: string, query: string, maxResults = 5) =>
    post('/arxiv/fetch', ownerId, {
      query, max_results: maxResults, auto_ingest: false,
    }, 600_000).then(r => json<import('./types').ArxivPipelineResponse>(r)),

  processPending: (ownerId: string) =>
    post('/arxiv/process-pending', ownerId, {}, 1_800_000).then(r => json<Record<string, number>>(r)),
}

// ══════════════════════════════════════════════════════════════
//  Summary / Survey
// ══════════════════════════════════════════════════════════════

export const summaryApi = {
  summarize: (ownerId: string, arxivId: string, lang = 'zh') =>
    post('/summarize', ownerId, { arxiv_id: arxivId, lang }).then(r => json<import('./types').SummarizeResponse>(r)),

  survey: (ownerId: string, query: string, topK = 10, lang = 'zh') =>
    post('/survey', ownerId, { query, top_k: topK, lang }).then(r => json<import('./types').SurveyResponse>(r)),
}

// ══════════════════════════════════════════════════════════════
//  Citations
// ══════════════════════════════════════════════════════════════

export const citationsApi = {
  stats: (ownerId: string) =>
    get('/citations/stats', ownerId).then(r => json<import('./types').CitationStats>(r)),

  extract: (ownerId: string, arxivIds?: string[]) =>
    post('/citations/extract', ownerId, arxivIds).then(r => json<unknown>(r)),
}

// ══════════════════════════════════════════════════════════════
//  Queries / History
// ══════════════════════════════════════════════════════════════

export const queriesApi = {
  list: (ownerId: string, limit = 20) =>
    get('/queries', ownerId, { limit }).then(r => json<import('./types').QueryListResponse>(r)),

  clear: (ownerId: string) =>
    del('/queries', ownerId).then(r => json<unknown>(r)),
}

// ══════════════════════════════════════════════════════════════
//  Collections
// ══════════════════════════════════════════════════════════════

export const collectionsApi = {
  list: (ownerId: string, limit = 50, offset = 0) =>
    get('/collections', ownerId, { limit, offset }).then(r => json<{ collections: import('./types').Collection[]; total: number }>(r)),

  create: (ownerId: string, name: string, description = '') =>
    post('/collections', ownerId, { name, description }).then(r => json<import('./types').Collection>(r)),

  delete: (ownerId: string, collectionId: number) =>
    del(`/collections/${collectionId}`, ownerId).then(r => json<unknown>(r)),

  addPaper: (ownerId: string, collectionId: number, paperId: number) =>
    post(`/collections/${collectionId}/papers`, ownerId, { paper_id: paperId }).then(r => json<unknown>(r)),

  listPapers: (ownerId: string, collectionId: number, limit = 50, offset = 0) =>
    get(`/collections/${collectionId}/papers`, ownerId, { limit, offset }).then(r => json<{ papers: import('./types').Paper[]; total: number }>(r)),
}

// Also expose content endpoint
export const contentApi = {
  get: (ownerId: string, arxivId: string) =>
    get(`/papers/${arxivId}/content`, ownerId).then(r => json<{ sections: { title: string; content: string; subsections: { title: string; content: string }[] }[]; total: number }>(r)),
}

// ══════════════════════════════════════════════════════════════
//  Cache
// ══════════════════════════════════════════════════════════════

export const cacheApi = {
  stats: (ownerId: string) =>
    get('/cache/stats', ownerId).then(r => json<import('./types').CacheStats>(r)),

  clear: (ownerId: string, kind = 'all') =>
    del(`/cache/clear?kind=${kind}`, ownerId).then(r => json<unknown>(r)),
}

// ══════════════════════════════════════════════════════════════
//  Config
// ══════════════════════════════════════════════════════════════

export const configApi = {
  get: () => fetch('/api/config').then(r => json<Record<string, any>>(r)),
}

// ══════════════════════════════════════════════════════════════
//  Export
// ══════════════════════════════════════════════════════════════

export const exportApi = {
  papersUrl: (_ownerId: string, fmt = 'json', limit = 200) =>
    `${API_BASE}/export/papers?fmt=${fmt}&limit=${limit}`,

  queriesUrl: (_ownerId: string, fmt = 'json', limit = 500) =>
    `${API_BASE}/export/queries?fmt=${fmt}&limit=${limit}`,
}

// ══════════════════════════════════════════════════════════════
//  Fetch History
// ══════════════════════════════════════════════════════════════

export const fetchApi = {
  history: (ownerId: string, limit = 20, offset = 0) =>
    get('/fetch/history', ownerId, { limit, offset }).then(r => json<import('./types').FetchHistoryResponse>(r)),
  historyDetail: (ownerId: string, id: number) =>
    get(`/fetch/history/${id}`, ownerId).then(r => json<import('./types').FetchRecord>(r)),
}
