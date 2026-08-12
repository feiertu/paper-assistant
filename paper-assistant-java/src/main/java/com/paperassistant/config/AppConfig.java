package com.paperassistant.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * Typed application configuration mirroring the Python project's {@code config.py}.
 *
 * <p>All values bind from the {@code paper-assistant.*} namespace (see
 * {@code application.yml}), which in turn honors the original Python
 * environment variables (e.g. {@code ARXIV_MAX_RESULTS}, {@code CHUNK_SIZE}).
 * Every record component is normalized in the compact constructor with the
 * same defaults the Python module uses, so the record is safe to construct
 * programmatically (e.g. in tests) even when a property is absent.
 *
 * <p>Task-specific LLM models fall back to {@code llmModel} via the
 * {@code effectiveLlm*Model()} methods, matching the Python behavior of
 * {@code LLM_QA_MODEL = _env("LLM_QA_MODEL", "") or LLM_MODEL}.
 */
@ConfigurationProperties(prefix = "paper-assistant")
public record AppConfig(

    // ---------- Paths ----------
    /** Base data directory (Python: PAPER_ASSISTANT_DATA_DIR / PROJECT_ROOT/data). */
    String dataDir,
    /** Where raw downloaded PDFs are stored. */
    String rawPdfDir,
    /** Where parsed / extracted text is stored. */
    String parsedDir,
    /** ChromaDB / vector index directory. */
    String chromaDir,
    /** Processed output directory. */
    String processedDir,
    /** Log output directory. */
    String logDir,

    // ---------- arXiv fetch ----------
    /** arXiv query string. */
    String arxivQuery,
    /** Max number of arXiv results to fetch per run. */
    Integer arxivMaxResults,
    /** HTTP request timeout (seconds) for arXiv API calls. */
    Integer arxivRequestTimeout,
    /** Delay between consecutive PDF downloads (seconds). */
    Double pdfDownloadDelay,

    // ---------- PDF parsing ----------
    /** Parser backend: pymupdf | docling | grobid. */
    String pdfParser,
    /** Minimum body text size threshold (pt) for pymupdf mode. */
    Double pdfMinBodySize,

    // ---------- Text chunking ----------
    /** Target chunk size (characters/tokens). */
    Integer chunkSize,
    /** Overlap between adjacent chunks. */
    Integer chunkOverlap,

    // ---------- Embedding ----------
    /** Comma-separated providers: openai | voyage | local (e.g. "openai,voyage"). */
    String embeddingProvider,
    /** Embedding model name (e.g. text-embedding-3-large, BAAI/bge-m3). */
    String embeddingModel,
    /** Embedding vector dimensionality. */
    Integer embeddingDim,
    /** Embedding batch size. */
    Integer embeddingBatchSize,
    /** Optional standalone embedding API key (falls back to openaiApiKey). */
    String embeddingApiKey,
    /** Optional standalone embedding base URL (falls back to openaiBaseUrl). */
    String embeddingBaseUrl,
    /** RRF fusion: top-N candidates taken from each retrieval path. */
    Integer rrfTopN,
    /** RRF smoothing constant. */
    Integer rrfK,

    // ---------- LLM ----------
    /** OpenAI-compatible API key. */
    String openaiApiKey,
    /** OpenAI-compatible base URL. */
    String openaiBaseUrl,
    /** Default LLM model name. */
    String llmModel,
    /** Default LLM sampling temperature. */
    Double llmTemperature,
    /** Default LLM max output tokens. */
    Integer llmMaxTokens,
    /** RAG QA model override (blank = fall back to llmModel). */
    String llmQaModel,
    /** Single-document summary model override. */
    String llmSummaryModel,
    /** Survey-generation model override. */
    String llmSurveyModel,

    // ---------- Cache ----------
    /** Master switch for the Caffeine caches. */
    Boolean cacheEnabled,
    /** Max entries for the LLM cache (brief spells it cacheLlmMaxsize). */
    Integer cacheLlmMaxsize,
    /** LLM cache TTL (seconds, 1800 = 30 min). */
    Integer cacheLlmTtl,
    /** Max entries for the embedding cache. */
    Integer cacheEmbedMaxsize,
    /** Embedding cache TTL (seconds, 86400 = 24 h). */
    Integer cacheEmbedTtl,

    // ---------- API auth / rate limiting ----------
    /** Enable simple API-key authentication. */
    Boolean apiAuthEnabled,
    /** Static API key used when apiAuthEnabled is true. */
    String apiAuthKey,
    /** Global rate limit, e.g. "30/minute". */
    String apiRateLimit,
    /** Comma-separated allowed CORS origins (blank = permissive). */
    String apiCorsOrigins,

    // ---------- Agent ----------
    /** Agent-specific model override. */
    String llmAgentModel,
    /** Max reasoning iterations for the agent. */
    Integer agentMaxIterations,
    /** Agent sampling temperature. */
    Double agentTemperature,
    /** Max context tokens for the agent. */
    Integer agentMaxContextTokens,
    /** Tool-call retry count. */
    Integer agentToolRetry,

    // ---------- Voyage AI ----------
    /** Voyage AI API key (hybrid retrieval / embeddings). */
    String voyageApiKey,

    // ---------- RAG retrieval ----------
    /** Top-K documents retrieved per RAG query. */
    Integer ragTopK,
    /** Vector collection / index name. */
    String ragCollectionName,

    // ---------- HNSW index parameters ----------
    /** HNSW max connections. */
    Integer hnswM,
    /** HNSW build-time search depth. */
    Integer hnswEfConstruction,
    /** HNSW query-time search depth. */
    Integer hnswEfSearch,

    // ---------- Hybrid retrieval (v3) ----------
    /** Enable hybrid (dense + sparse) retrieval. */
    Boolean hybridRetrieval,
    /** Enable BM25 sparse retrieval. */
    Boolean bm25Enabled,
    /** Enable Cross-Encoder re-ranking. */
    Boolean rerankerEnabled,
    /** BM25 weight in RRF fusion (0-1). */
    Double bm25Weight,

    // ---------- API service ----------
    /** Bind host for the HTTP API. */
    String apiHost,
    /** Bind port for the HTTP API. */
    Integer apiPort,

    // ---------- Multi-user isolation ----------
    /** Session cookie name. */
    String sessionCookie,
    /** Session TTL in days. */
    Integer sessionTtlDays,

    // ---------- UI ----------
    /** Streamlit / UI title. */
    String uiTitle
) {

    /**
     * Applies the same defaults the Python {@code config.py} uses, so a record
     * built from a partial property set is never null/zero in a way that would
     * NPE at runtime. Order matters: {@code dataDir} is normalized first so the
     * derived path components can reference it.
     */
    public AppConfig {
        dataDir = nz(dataDir, "data");
        rawPdfDir = nz(rawPdfDir, dataDir + "/raw");
        parsedDir = nz(parsedDir, dataDir + "/parsed");
        chromaDir = nz(chromaDir, dataDir + "/chroma_db");
        processedDir = nz(processedDir, dataDir + "/processed");
        logDir = nz(logDir, "logs");

        arxivQuery = nz(arxivQuery, "cat:cs.AI AND ti:learning");
        arxivMaxResults = nz(arxivMaxResults, 5);
        arxivRequestTimeout = nz(arxivRequestTimeout, 60);
        pdfDownloadDelay = nz(pdfDownloadDelay, 3.0);

        pdfParser = nz(pdfParser, "pymupdf");
        pdfMinBodySize = nz(pdfMinBodySize, 6.5);

        chunkSize = nz(chunkSize, 1000);
        chunkOverlap = nz(chunkOverlap, 200);

        embeddingProvider = nz(embeddingProvider, "openai,voyage");
        embeddingModel = nz(embeddingModel, "text-embedding-3-large");
        embeddingDim = nz(embeddingDim, 1024);
        embeddingBatchSize = nz(embeddingBatchSize, 32);
        embeddingApiKey = nz(embeddingApiKey, null);
        embeddingBaseUrl = nz(embeddingBaseUrl, null);
        rrfTopN = nz(rrfTopN, 20);
        rrfK = nz(rrfK, 60);

        openaiApiKey = nz(openaiApiKey, null);
        openaiBaseUrl = nz(openaiBaseUrl, null);
        llmModel = nz(llmModel, "qwen-2.5-72b-instruct");
        llmTemperature = nz(llmTemperature, 0.2);
        llmMaxTokens = nz(llmMaxTokens, 1024);
        llmQaModel = nz(llmQaModel, null);
        llmSummaryModel = nz(llmSummaryModel, null);
        llmSurveyModel = nz(llmSurveyModel, null);

        cacheEnabled = nz(cacheEnabled, true);
        cacheLlmMaxsize = nz(cacheLlmMaxsize, 200);
        cacheLlmTtl = nz(cacheLlmTtl, 1800);
        cacheEmbedMaxsize = nz(cacheEmbedMaxsize, 2000);
        cacheEmbedTtl = nz(cacheEmbedTtl, 86400);

        apiAuthEnabled = nz(apiAuthEnabled, false);
        apiAuthKey = nz(apiAuthKey, null);
        apiRateLimit = nz(apiRateLimit, "30/minute");
        apiCorsOrigins = nz(apiCorsOrigins, null);

        llmAgentModel = nz(llmAgentModel, null);
        agentMaxIterations = nz(agentMaxIterations, 10);
        agentTemperature = nz(agentTemperature, 0.1);
        agentMaxContextTokens = nz(agentMaxContextTokens, 8000);
        agentToolRetry = nz(agentToolRetry, 2);

        voyageApiKey = nz(voyageApiKey, null);

        ragTopK = nz(ragTopK, 5);
        ragCollectionName = nz(ragCollectionName, "knowledge");

        hnswM = nz(hnswM, 32);
        hnswEfConstruction = nz(hnswEfConstruction, 200);
        hnswEfSearch = nz(hnswEfSearch, 100);

        hybridRetrieval = nz(hybridRetrieval, true);
        bm25Enabled = nz(bm25Enabled, true);
        rerankerEnabled = nz(rerankerEnabled, true);
        bm25Weight = nz(bm25Weight, 0.3);

        apiHost = nz(apiHost, "127.0.0.1");
        apiPort = nz(apiPort, 8000);

        sessionCookie = nz(sessionCookie, "paper_session");
        sessionTtlDays = nz(sessionTtlDays, 30);

        uiTitle = nz(uiTitle, "Paper Assistant");
    }

    // ---------- Task-specific LLM model resolution ----------

    /** Effective model for RAG Q&A (falls back to {@link #llmModel}). */
    public String effectiveLlmQaModel() {
        return nz(llmQaModel, llmModel);
    }

    /** Effective model for single-document summaries. */
    public String effectiveLlmSummaryModel() {
        return nz(llmSummaryModel, llmModel);
    }

    /** Effective model for survey generation. */
    public String effectiveLlmSurveyModel() {
        return nz(llmSurveyModel, llmModel);
    }

    /** Effective model for the agent. */
    public String effectiveLlmAgentModel() {
        return nz(llmAgentModel, llmModel);
    }

    // ---------- Defaulting helpers ----------

    private static String nz(String value, String fallback) {
        return (value == null || value.isBlank()) ? fallback : value;
    }

    private static int nz(Integer value, int fallback) {
        return value == null ? fallback : value;
    }

    private static double nz(Double value, double fallback) {
        return value == null ? fallback : value;
    }

    private static boolean nz(Boolean value, boolean fallback) {
        return value == null ? fallback : value;
    }
}
