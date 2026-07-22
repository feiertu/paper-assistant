/** API response types for Paper Assistant */

export interface Paper {
  id: number
  arxiv_id: string
  title: string
  authors: string
  abstract: string
  published: string
  source: string
  pdf_url: string
  ingest_status: 'ingested' | 'pending' | 'failed'
  chunk_count: number
  created_at: string
}

export interface PaperListResponse {
  papers: Paper[]
  total: number
  limit: number
  offset: number
}

export interface PaperChunk {
  id: string
  document: string
  metadata: {
    arxiv_id?: string
    title?: string
    section_title?: string
    page?: number
    [key: string]: unknown
  }
}

export interface ChunkListResponse {
  chunks: PaperChunk[]
  total: number
}

export interface RetrieveHit {
  id: string
  document: string
  metadata: Record<string, unknown>
  distance?: number
}

export interface RetrieveResponse {
  hits: RetrieveHit[]
  query: string
}

export interface RagQueryResponse {
  answer: string
  hits?: RetrieveHit[]
  query: string
}

export interface StoreStats {
  count: number
  [key: string]: unknown
}

export interface CacheStats {
  llm: {
    hits: number
    misses: number
    hit_rate: number
    hit_rate_pct: string
    total_requests: number
    estimated_tokens_saved: number
    efficiency: string
    size: number
    maxsize: number
  }
  embed: {
    hits: number
    misses: number
    hit_rate: number
    hit_rate_pct: string
    total_requests: number
    size: number
    maxsize: number
  }
}

export interface CitationGraph {
  cites: CitationEntry[]
  cited_by: CitationEntry[]
}

export interface CitationEntry {
  cited_arxiv_id?: string
  cited_title?: string
  citing_arxiv_id?: string
  citing_title?: string
  in_db: boolean
}

export interface CitationStats {
  total: number
}

export interface QueryRecord {
  id: number
  query_text: string
  answer_text: string
  lang: string
  hit_count: number
  created_at: string
}

export interface QueryListResponse {
  queries: QueryRecord[]
  total: number
}

export interface SummarizeResponse {
  summary: string
  arxiv_id: string
}

export interface SurveyResponse {
  survey: string
  query: string
}

export interface IngestResult {
  papers: number
  chunks: number
  error?: string
}

export interface ArxivPipelineStep {
  step: string
  count?: number
  success?: number
  failed?: number
  papers?: number
  chunks?: number
}

export interface ArxivPipelineResponse {
  steps: ArxivPipelineStep[]
}

export interface AgentStreamEvent {
  type: 'thinking' | 'tool_call' | 'tool_result' | 'answer_chunk' | 'error' | 'usage'
  content?: string
  tool?: string
  result?: string
  message?: string
  total_tokens?: number
  steps?: number
  duration_ms?: number
}

export interface SimilarPaper {
  arxiv_id: string
  title: string
  score: number
  shared_chunks: number
}

export interface RecommendResponse {
  similar: SimilarPaper[]
}

export interface AnalyzeResponse {
  analysis: string
}

export interface Collection {
  id: number
  name: string
  description: string
  paper_count: number
  created_at: string
}

export interface SkippedPaper { id: string; title: string }
export interface FetchRecord {
  id: number; query_text: string; max_results: number;
  total_found: number; fetched: number; skipped: number;
  download_success: number; download_failed: number;
  parse_success: number; parse_failed: number; ingested: number;
  skipped_papers: SkippedPaper[]; owner_id: string; created_at: string;
}
export interface FetchHistoryResponse { records: FetchRecord[]; total: number }
