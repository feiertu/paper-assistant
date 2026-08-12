package com.paperassistant.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.paperassistant.config.AppConfig;
import com.paperassistant.entity.Paper;
import com.paperassistant.entity.QueryRecord;
import com.paperassistant.llm.ChatClientService;
import com.paperassistant.llm.PromptTemplates;
import com.paperassistant.repository.PaperRepository;
import com.paperassistant.repository.QueryRecordRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.openai.OpenAiChatOptions;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;
import reactor.core.publisher.Flux;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * RAG orchestration service — ties together embedding, retrieval, LLM chat,
 * and query history persistence, mirroring the Python
 * {@code src/rag/orchestrator.py}.
 *
 * <p>Every public method that calls the LLM inspects the
 * {@code OpenAI API key} configuration; when absent the {@code chatClient} is
 * {@code null} and the method throws an {@link IllegalStateException} with a
 * clear message (same contract as {@link EmbedService}).
 *
 * <p><b>Streaming:</b> {@link #answerRagStream} returns a {@link Flux}{@code <String>}
 * where each element is an SSE-formatted event ({@code data: <token>\n\n}).
 */
@Service
public class RagService {

    private static final Logger log = LoggerFactory.getLogger(RagService.class);

    /** Default text length passed to the LLM summariser (chars). */
    private static final int SUMMARY_MAX_CHARS = 8000;
    /** Default max words for summary prompts. */
    private static final int SUMMARY_MAX_WORDS = 200;
    /** Default max words for survey prompts. */
    private static final int SURVEY_MAX_WORDS = 800;

    private final AppConfig config;
    private final EmbedService embedService;
    private final Bm25Service bm25Service;
    private final PaperRepository paperRepository;
    private final ParseService parseService;
    private final QueryRecordRepository queryRecordRepository;
    private final ChatClientService chatClientService;
    private final ObjectMapper objectMapper;

    /**
     * Nullable — only built when {@link AppConfig#openaiApiKey()} is configured.
     * Every LLM-using method guards with {@link #requireChatClient()}.
     */
    private final ChatClient chatClient;

    public RagService(AppConfig config,
                      EmbedService embedService,
                      Bm25Service bm25Service,
                      PaperRepository paperRepository,
                      ParseService parseService,
                      QueryRecordRepository queryRecordRepository,
                      ObjectMapper objectMapper,
                      ChatClientService chatClientService,
                      ObjectProvider<ChatClient.Builder> chatClientBuilderProvider) {
        this.config = config;
        this.embedService = embedService;
        this.bm25Service = bm25Service;
        this.paperRepository = paperRepository;
        this.parseService = parseService;
        this.queryRecordRepository = queryRecordRepository;
        this.objectMapper = objectMapper;
        this.chatClientService = chatClientService;

        this.chatClient = buildChatClient(chatClientBuilderProvider);

        log.info("RagService initialized: ragTopK={} parsedDir={} llmModel={} chatClient={}",
                config.ragTopK(), config.parsedDir(), config.llmModel(),
                chatClient != null ? "available" : "absent (no API key)");
    }

    // ──────────────────────────────────────────────
    //  Data ingestion
    // ──────────────────────────────────────────────

    /**
     * Ingests all parsed JSON files from {@code config.parsedPath()} into the
     * vector database (pgvector via {@link PaperRepository}).
     *
     * <p>Algorithm (mirrors Python {@code ingest_parsed_dir()}):
     * <ol>
     *   <li>Walk {@code parsedDir} for {@code *.json} files.</li>
     *   <li>For each file: read JSON, extract section content, concatenate text.</li>
     *   <li>Batch-embed paper texts with {@link EmbedService#embed(List)} in
     *       batches of {@link AppConfig#embeddingBatchSize()}.</li>
     *   <li>Save each paper's embedding + metadata via {@link PaperRepository},
     *       setting {@code ingestStatus = "ingested"} and {@code chunkCount}.</li>
     * </ol>
     *
     * @param parsedDir optional override; {@code null} or blank uses {@code config.parsedDir()}
     * @param ownerId   multi-user isolation identifier
     * @return status map with keys {@code status/papers/chunks/embedding_batches}
     */
    public Map<String, Object> ingestParsedDir(String parsedDir, String ownerId) {
        String resolvedDir = (parsedDir != null && !parsedDir.isBlank())
                ? parsedDir : config.parsedDir();
        Path dir = Path.of(resolvedDir);
        if (!Files.isDirectory(dir)) {
            return Map.of("error", "目录不存在: " + dir);
        }

        List<Path> jsonFiles;
        try (var stream = Files.list(dir)) {
            jsonFiles = stream
                    .filter(Files::isRegularFile)
                    .filter(p -> p.getFileName().toString().endsWith(".json"))
                    .sorted()
                    .toList();
        } catch (IOException e) {
            return Map.of("error", "读取目录失败: " + e.getMessage());
        }

        if (jsonFiles.isEmpty()) {
            return Map.of("error", "在 " + dir + " 中未找到任何 JSON 文件");
        }

        int paperCount = jsonFiles.size();
        int totalChunks = 0;
        int batchSize = Math.max(1, config.embeddingBatchSize());

        // Phase 1: read all JSONs, collect texts and metadata
        record PaperIngest(String arxivId, String text, String title,
                           String authors, String abstractText, String published,
                           String pdfUrl, String source) {}

        List<PaperIngest> papers = new ArrayList<>();
        for (Path fp : jsonFiles) {
            try {
                JsonNode root = objectMapper.readTree(fp.toFile());
                String arxivId = fp.getFileName().toString().replaceAll("\\.json$", "");

                // Extract metadata
                JsonNode metaNode = root.get("metadata");
                String title = jsonString(metaNode, "title");
                String authors = jsonString(metaNode, "author");
                String published = jsonString(metaNode, "creationDate");
                String pdfUrl = jsonString(metaNode, "pdf_url");
                String source = jsonString(metaNode, "source");
                if (source.isEmpty()) {
                    source = "pymupdf";
                }

                // Extract abstract: prefer metadata.abstract, else first "Abstract" section
                String abstractText = jsonString(metaNode, "abstract");
                if (abstractText.isEmpty()) {
                    JsonNode sections = root.get("sections");
                    if (sections != null && sections.isArray()) {
                        for (JsonNode sec : sections) {
                            String secTitle = jsonString(sec, "title").trim();
                            if ("abstract".equalsIgnoreCase(secTitle)) {
                                abstractText = jsonString(sec, "content").trim();
                                break;
                            }
                        }
                    }
                }
                if (abstractText.length() > 3000) {
                    abstractText = abstractText.substring(0, 3000) + "…";
                }

                // Concatenate all section content
                StringBuilder textBuilder = new StringBuilder();
                JsonNode sections = root.get("sections");
                if (sections != null && sections.isArray()) {
                    for (JsonNode sec : sections) {
                        appendSectionText(textBuilder, sec);
                    }
                }
                String fullText = textBuilder.toString().trim();

                // Truncate to a reasonable embedding length (approx 8k chars ~= 2k tokens)
                if (fullText.length() > SUMMARY_MAX_CHARS) {
                    fullText = fullText.substring(0, SUMMARY_MAX_CHARS);
                }

                papers.add(new PaperIngest(arxivId, fullText, title, authors,
                        abstractText, published, pdfUrl, source));
                log.debug("Read paper: {} text_len={} sections={}",
                        arxivId, fullText.length(),
                        sections != null ? sections.size() : 0);

            } catch (IOException e) {
                log.warn("Failed to read JSON file {}: {}", fp.getFileName(), e.getMessage());
            }
        }

        if (papers.isEmpty()) {
            return Map.of("error", "没有成功读取任何论文");
        }

        // Phase 2: batch embed + save
        List<String> allTexts = papers.stream().map(PaperIngest::text).toList();
        int batches = 0;
        for (int start = 0; start < allTexts.size(); start += batchSize) {
            int end = Math.min(start + batchSize, allTexts.size());
            List<String> batchTexts = allTexts.subList(start, end);
            List<float[]> embeddings = embedService.embed(batchTexts);

            for (int j = 0; j < batchTexts.size(); j++) {
                PaperIngest pi = papers.get(start + j);

                // Upsert: find existing paper or create new one
                Optional<Paper> existing = paperRepository
                        .findByArxivIdAndOwnerId(pi.arxivId(), ownerId != null ? ownerId : "");
                Paper paper;
                if (existing.isPresent()) {
                    paper = existing.get();
                } else {
                    paper = Paper.builder()
                            .arxivId(pi.arxivId())
                            .ownerId(ownerId != null ? ownerId : "")
                            .createdAt(LocalDateTime.now())
                            .build();
                }

                paper.setTitle(pi.title());
                paper.setAuthors(pi.authors());
                paper.setAbstractText(pi.abstractText());
                paper.setPublished(pi.published());
                paper.setPdfUrl(pi.pdfUrl());
                paper.setSource(pi.source());
                paper.setIngestStatus("ingested");
                paper.setChunkCount(1); // one embedding = one conceptual "chunk" for this paper
                paper.setEmbedding(embeddings.get(j));

                paperRepository.save(paper);
                log.debug("Saved paper: {} status=ingested", pi.arxivId());
            }

            totalChunks += batchTexts.size();
            batches++;
            log.info("Embedding batch {}/{}: {}-{} ({}/{} papers)",
                    batches, (int) Math.ceil((double) allTexts.size() / batchSize),
                    start, end, batchTexts.size(), allTexts.size());
        }

        log.info("Ingestion complete: papers={} embeddings={} batches={}",
                paperCount, totalChunks, batches);

        return Map.of(
                "status", "ok",
                "papers", paperCount,
                "chunks", totalChunks,
                "embedding_batches", batches
        );
    }

    /**
     * Ingests a single text string into the vector store (for manual ad-hoc
     * content), mirroring Python {@code ingest_text()}.
     */
    public Map<String, Object> ingestText(String text, Map<String, String> metadata, String ownerId) {
        if (text == null || text.isBlank()) {
            return Map.of("error", "文本内容为空");
        }

        String title = metadata != null ? metadata.getOrDefault("title", "") : "";
        String arxivId = metadata != null ? metadata.getOrDefault("arxiv_id", "manual_" + System.currentTimeMillis()) : "manual_" + System.currentTimeMillis();
        String source = metadata != null ? metadata.getOrDefault("source", "manual") : "manual";

        // Truncate for embedding
        String truncatedText = text.length() > SUMMARY_MAX_CHARS
                ? text.substring(0, SUMMARY_MAX_CHARS) : text;

        float[] embedding = embedService.embedQuery(truncatedText);

        Paper paper = Paper.builder()
                .arxivId(arxivId)
                .title(title)
                .source(source)
                .ingestStatus("ingested")
                .chunkCount(1)
                .ownerId(ownerId != null ? ownerId : "")
                .embedding(embedding)
                .build();
        paperRepository.save(paper);

        log.info("ingestText: arxivId={} chars={}", arxivId, truncatedText.length());
        return Map.of("status", "ok", "chunks", 1);
    }

    // ──────────────────────────────────────────────
    //  Retrieval
    // ──────────────────────────────────────────────

    /**
     * Hybrid retrieval wrapping {@link EmbedService#hybridRetrieve}, mirroring
     * Python {@code retrieve()}.
     *
     * @param query   search text
     * @param topK    max results; {@code null} or {@code <= 0} uses {@code config.ragTopK()}
     * @param ownerId multi-user isolation identifier
     * @return {@code {"hits": [...], "query": "<query>"}}
     */
    public Map<String, Object> retrieve(String query, Integer topK, String ownerId) {
        int k = (topK == null || topK <= 0) ? config.ragTopK() : topK;
        List<Map<String, Object>> hits = embedService.hybridRetrieve(query, k,
                ownerId != null ? ownerId : "");

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("hits", hits);
        result.put("query", query);
        return result;
    }

    // ──────────────────────────────────────────────
    //  RAG Q&A
    // ──────────────────────────────────────────────

    /**
     * Non-streaming RAG Q&A: retrieve → build context → call LLM → persist
     * query history, mirroring Python {@code answer_rag()}.
     *
     * @param query   user question
     * @param topK    retrieval count (null = use config default)
     * @param lang    "zh" or "en"
     * @param ownerId multi-user isolation
     * @return {@code {"query": ..., "answer": ..., "sources": [{"arxiv_id":..., "title":...}]}}
     */
    public Map<String, Object> answerRag(String query, Integer topK, String lang, String ownerId) {
        requireChatClient();

        if (query == null || query.isBlank()) {
            return Map.of("error", "查询内容不能为空");
        }

        Map<String, Object> retrieveResult = retrieve(query, topK, ownerId);
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> hits = (List<Map<String, Object>>) retrieveResult.get("hits");
        if (hits == null || hits.isEmpty()) {
            return Map.of(
                    "query", query,
                    "answer", "未找到相关论文片段，请尝试修改查询。",
                    "sources", List.of()
            );
        }

        // Build context and call LLM
        String context = PromptTemplates.formatContext(hits);
        String template = "zh".equals(lang) ? PromptTemplates.RAG_QA_PROMPT_ZH : PromptTemplates.RAG_QA_PROMPT_EN;
        String userPrompt = template.replace("{context}", context).replace("{query}", query);

        String effectiveModel = config.effectiveLlmQaModel();
        log.info("answerRag: model={} query={} hits={} lang={}",
                effectiveModel, truncate(query, 60), hits.size(), lang);

        String answer = chatClient.prompt()
                .system(PromptTemplates.RAG_QA_SYSTEM)
                .user(userPrompt)
                .options(OpenAiChatOptions.builder()
                        .model(effectiveModel)
                        .temperature(config.llmTemperature())
                        .maxTokens(config.llmMaxTokens())
                        .build())
                .call()
                .content();

        // Persist query history
        saveQueryHistory(query, answer, lang, hits.size(), ownerId);

        // Build source list for the response
        List<Map<String, String>> sources = extractSources(hits);

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("query", query);
        result.put("answer", answer);
        result.put("sources", sources);
        return result;
    }

    /**
     * Streaming RAG Q&A: same pipeline as {@link #answerRag} but returns a
     * {@link Flux}{@code <String>} of SSE-formatted token chunks
     * ({@code data: <token>\n\n}).
     *
     * <p>Query history is persisted after the stream completes (via
     * {@code doOnComplete}). Each emitted element is a single SSE event.
     *
     * @param query   user question
     * @param topK    retrieval count (null = use config default)
     * @param lang    "zh" or "en"
     * @param ownerId multi-user isolation
     * @return cold SSE flux — subscribe to begin streaming
     */
    public Flux<String> answerRagStream(String query, Integer topK, String lang, String ownerId) {
        requireChatClient();

        if (query == null || query.isBlank()) {
            return Flux.just(sseEvent("[ERROR] 查询内容不能为空"));
        }

        Map<String, Object> retrieveResult = retrieve(query, topK, ownerId);
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> hits = (List<Map<String, Object>>) retrieveResult.get("hits");
        if (hits == null || hits.isEmpty()) {
            return Flux.just(sseEvent("未找到相关论文片段，请尝试修改查询。"));
        }

        String context = PromptTemplates.formatContext(hits);
        String template = "zh".equals(lang) ? PromptTemplates.RAG_QA_PROMPT_ZH : PromptTemplates.RAG_QA_PROMPT_EN;
        String userPrompt = template.replace("{context}", context).replace("{query}", query);

        String effectiveModel = config.effectiveLlmQaModel();
        log.info("answerRagStream: model={} query={} hits={} lang={}",
                effectiveModel, truncate(query, 60), hits.size(), lang);

        StringBuilder fullAnswer = new StringBuilder();

        return chatClient.prompt()
                .system(PromptTemplates.RAG_QA_SYSTEM)
                .user(userPrompt)
                .options(OpenAiChatOptions.builder()
                        .model(effectiveModel)
                        .temperature(config.llmTemperature())
                        .maxTokens(config.llmMaxTokens())
                        .build())
                .stream()
                .content()
                .map(token -> {
                    fullAnswer.append(token);
                    return sseEvent(token);
                })
                .doOnComplete(() -> {
                    log.info("answerRagStream complete: answer_len={}", fullAnswer.length());
                    try {
                        saveQueryHistory(query, fullAnswer.toString(), lang,
                                hits.size(), ownerId);
                    } catch (Exception ex) {
                        log.warn("Failed to save query history after stream: {}", ex.getMessage());
                    }
                });
    }

    // ──────────────────────────────────────────────
    //  Single-document summary
    // ──────────────────────────────────────────────

    /**
     * Generates a structured summary for a single paper, mirroring Python
     * {@code summarize_paper()}.
     *
     * <p>Algorithm:
     * <ol>
     *   <li>Read parsed JSON from {@code config.parsedPath() / arxivId + ".json"}.</li>
     *   <li>Extract full text from sections, truncate to {@value #SUMMARY_MAX_CHARS} chars.</li>
     *   <li>Build SUMMARY prompt → call LLM with the summary model.</li>
     *   <li>Fallback: if the parsed JSON is missing, use the paper's abstract from
     *       the database (PaperRepository).</li>
     * </ol>
     *
     * @param arxivId arXiv identifier, e.g. "2606.13673v1"
     * @param lang    "zh" or "en"
     * @return summary text, or an error string prefixed with {@code [ERROR]}
     */
    public String summarizePaper(String arxivId, String lang) {
        requireChatClient();

        String text = extractPaperText(arxivId);
        if (text.isEmpty()) {
            // Fallback: use database abstract
            Optional<Paper> paperOpt = paperRepository.findByArxivIdAndOwnerId(arxivId, "");
            if (paperOpt.isPresent() && StringUtils.hasText(paperOpt.get().getAbstractText())) {
                text = paperOpt.get().getAbstractText();
            } else {
                return "[ERROR] 未找到解析文件且数据库中也无摘要数据: " + arxivId;
            }
        }

        if (text.length() > SUMMARY_MAX_CHARS) {
            text = text.substring(0, SUMMARY_MAX_CHARS) + "…";
        }

        String template = "zh".equals(lang) ? PromptTemplates.SUMMARY_PROMPT_ZH : PromptTemplates.SUMMARY_PROMPT_EN;
        String userPrompt = template
                .replace("{text}", text)
                .replace("{max_words}", String.valueOf(SUMMARY_MAX_WORDS));

        String effectiveModel = config.effectiveLlmSummaryModel();
        log.info("summarizePaper: model={} arxivId={} text_len={} lang={}",
                effectiveModel, arxivId, text.length(), lang);

        try {
            return chatClient.prompt()
                    .user(userPrompt)
                    .options(OpenAiChatOptions.builder()
                            .model(effectiveModel)
                            .temperature(config.llmTemperature())
                            .maxTokens(config.llmMaxTokens())
                            .build())
                    .call()
                    .content();
        } catch (Exception e) {
            return "摘要生成失败: " + e.getMessage();
        }
    }

    // ──────────────────────────────────────────────
    //  Survey
    // ──────────────────────────────────────────────

    /**
     * Multi-document survey generation: retrieve → format context → call LLM
     * with the survey model, mirroring Python {@code survey()}.
     *
     * @param query   search topic
     * @param topK    retrieval count (null = max of config default and 10)
     * @param lang    "zh" or "en"
     * @param ownerId multi-user isolation
     * @return survey text, or an informative message when no references are found
     */
    public String survey(String query, Integer topK, String lang, String ownerId) {
        requireChatClient();

        int k = (topK == null || topK <= 0)
                ? Math.max(config.ragTopK(), 10) : topK;

        Map<String, Object> retrieveResult = retrieve(query, k, ownerId);
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> hits = (List<Map<String, Object>>) retrieveResult.get("hits");

        if (hits == null || hits.isEmpty()) {
            return "未找到相关论文片段，无法生成综述。";
        }

        String context = PromptTemplates.formatContext(hits);
        String template = "zh".equals(lang) ? PromptTemplates.SURVEY_PROMPT_ZH : PromptTemplates.SURVEY_PROMPT_EN;
        String userPrompt = template
                .replace("{context}", context)
                .replace("{max_words}", String.valueOf(SURVEY_MAX_WORDS));

        String effectiveModel = config.effectiveLlmSurveyModel();
        log.info("survey: model={} query={} hits={} lang={}",
                effectiveModel, truncate(query, 60), hits.size(), lang);

        try {
            return chatClient.prompt()
                    .user(userPrompt)
                    .options(OpenAiChatOptions.builder()
                            .model(effectiveModel)
                            .temperature(config.llmTemperature())
                            .maxTokens(config.llmMaxTokens())
                            .build())
                    .call()
                    .content();
        } catch (Exception e) {
            return "综述生成失败: " + e.getMessage();
        }
    }

    // ──────────────────────────────────────────────
    //  Recommend similar + global analysis
    // ──────────────────────────────────────────────

    /**
     * Recommends papers similar to a given paper, mirroring Python
     * {@code recommend_similar()}.
     *
     * <p>Algorithm:
     * <ol>
     *   <li>Locate the source paper by {@code arxivId} and read its embedding
     *       vector (a single pgvector row per paper in this rewrite).</li>
     *   <li>Query pgvector for the closest papers via the {@code <=>} cosine
     *       distance operator (fetch {@code topK + 1} candidates so the source
     *       paper itself can be dropped).</li>
     *   <li>Exclude the source paper and papers without an embedding, then
     *       convert each candidate's cosine distance to a similarity score
     *       {@code 1 / (1 + distance)} (same formula as Python).</li>
     * </ol>
     *
     * <p>Each result is {@code {"arxiv_id", "title", "score", "shared_chunks"}};
     * {@code shared_chunks} is {@code 1} because every paper stores a single
     * embedding (one conceptual chunk). Returns an empty list when the source
     * paper is not found or has no embedding.
     *
     * @param arxivId source paper identifier
     * @param topK    max results (non-positive falls back to 5)
     * @return ordered list of similar papers, most similar first
     */
    public List<Map<String, Object>> recommendSimilar(String arxivId, int topK) {
        if (arxivId == null || arxivId.isBlank()) {
            return List.of();
        }
        int k = topK <= 0 ? 5 : topK;

        Optional<Paper> sourceOpt = paperRepository.findByArxivIdAndOwnerId(arxivId, "");
        if (sourceOpt.isEmpty() || sourceOpt.get().getEmbedding() == null
                || sourceOpt.get().getEmbedding().length == 0) {
            return List.of();
        }
        Paper source = sourceOpt.get();

        // Query k+1 candidates so we can drop the source paper and still return topK.
        String embeddingStr = Arrays.toString(source.getEmbedding());
        List<Paper> candidates = paperRepository.findSimilarByEmbedding(embeddingStr, "", k + 1);

        List<Map<String, Object>> results = new ArrayList<>(k);
        for (Paper candidate : candidates) {
            if (arxivId.equals(candidate.getArxivId())) {
                continue;
            }
            if (candidate.getEmbedding() == null || candidate.getEmbedding().length == 0) {
                continue;
            }
            if (results.size() >= k) {
                break;
            }
            double distance = cosineDistance(source.getEmbedding(), candidate.getEmbedding());
            double score = Math.round((1.0 / (1.0 + distance)) * 10_000.0) / 10_000.0;

            Map<String, Object> item = new LinkedHashMap<>();
            item.put("arxiv_id", candidate.getArxivId());
            item.put("title", candidate.getTitle() != null && !candidate.getTitle().isBlank()
                    ? candidate.getTitle() : candidate.getArxivId());
            item.put("score", score);
            item.put("shared_chunks", 1);
            results.add(item);
        }
        return results;
    }

    /**
     * Global paper analysis: gathers the metadata of all ingested papers and
     * asks the LLM for an overview, mirroring Python {@code analyze_all_papers()}.
     *
     * <p>Algorithm:
     * <ol>
     *   <li>Load up to 100 ingested papers for the owner.</li>
     *   <li>Build a context of {@code [n] arxiv_id | title / authors / date /
     *       abstract} for every paper (abstract truncated to 300 chars).</li>
     *   <li>Compose a Chinese or English system + user prompt asking the LLM to
     *       extract 3-5 theme keywords, categorize the papers, and summarize
     *       research trends.</li>
     *   <li>Call {@link ChatClientService#chat} with the QA model and return the
     *       analysis text.</li>
     * </ol>
     *
     * @param query   the user's specific question (blank uses the default prompt)
     * @param lang    {@code "zh"} or {@code "en"}
     * @param ownerId multi-user isolation identifier
     * @return analysis text, or an error string prefixed with {@code [ERROR]}
     */
    public String analyzeAllPapers(String query, String lang, String ownerId) {
        String owner = ownerId != null ? ownerId : "";
        List<Paper> all = paperRepository.findIngestedByOwnerId(owner);
        List<Paper> papers = all.size() > 100 ? all.subList(0, 100) : all;

        if (papers.isEmpty()) {
            return "[ERROR] 论文库中暂无论文，请先导入数据。";
        }

        StringBuilder context = new StringBuilder();
        for (int i = 0; i < papers.size(); i++) {
            Paper p = papers.get(i);
            String title = (p.getTitle() != null && !p.getTitle().isBlank())
                    ? p.getTitle() : p.getArxivId();
            String abstractText = p.getAbstractText() != null ? p.getAbstractText() : "";
            if (abstractText.length() > 300) {
                abstractText = abstractText.substring(0, 300);
            }
            String authors = (p.getAuthors() != null && !p.getAuthors().isBlank())
                    ? p.getAuthors() : "未知";
            if (authors.length() > 100) {
                authors = authors.substring(0, 100);
            }
            String published = (p.getPublished() != null && !p.getPublished().isBlank())
                    ? p.getPublished() : "未知";

            if (i > 0) {
                context.append("\n\n");
            }
            context.append("[").append(i + 1).append("] ").append(p.getArxivId())
                    .append(" | ").append(title).append('\n')
                    .append("    作者: ").append(authors).append(" | 日期: ").append(published).append('\n')
                    .append("    摘要: ").append(abstractText);
        }

        boolean zh = "zh".equals(lang);
        String systemPrompt = zh
                ? "你是学术论文分析助手，擅长从大量论文中提炼研究方向、主题和方法论趋势。"
                : "You are an academic paper analysis assistant, skilled at extracting "
                        + "research directions and methodology trends from large paper collections.";
        String defaultQuery = zh
                ? "请总结这些论文共同关注的研究方向、主要方法和核心发现。用 3-5 个主题词概括，并列出每篇论文的核心贡献。"
                : "Please summarize the research directions, main methods, and core findings "
                        + "these papers share. Use 3-5 theme keywords, and list each paper's core contribution.";
        String actualQuery = (query != null && !query.isBlank()) ? query : defaultQuery;

        String userPrompt = zh
                ? "以下是论文库中全部 " + papers.size() + " 篇论文的元数据：\n\n" + context
                        + "\n\n用户问题：" + actualQuery
                        + "\n\n要求：\n1. 先提炼 3-5 个共同主题词\n2. 按主题分类讨论论文\n"
                        + "3. 总结整体研究趋势和方法论特点\n4. 严格基于提供的元数据，不编造"
                : "Here are the metadata for all " + papers.size() + " papers in the library:\n\n" + context
                        + "\n\nUser question: " + actualQuery
                        + "\n\nRequirements:\n1. First extract 3-5 common theme keywords\n"
                        + "2. Categorize papers by theme\n3. Summarize overall research trends and methodology patterns\n"
                        + "4. Strictly based on provided metadata, no fabrication";

        String effectiveModel = config.effectiveLlmQaModel();
        log.info("analyzeAllPapers: model={} papers={} lang={}",
                effectiveModel, papers.size(), lang);

        // ChatClientService.chat() itself throws IllegalStateException when no API
        // key is configured (same requireChatClient contract as this class).
        String result = chatClientService.chat(
                ChatClientService.messages(systemPrompt, userPrompt),
                effectiveModel, config.llmTemperature());
        return result != null ? result : "[ERROR] 分析生成失败：模型返回为空";
    }

    // ──────────────────────────────────────────────
    //  Private helpers
    // ──────────────────────────────────────────────

    /**
     * Returns the ChatClient or throws if it was never built (missing API key).
     */
    private ChatClient requireChatClient() {
        if (chatClient == null) {
            throw new IllegalStateException(
                    "OpenAI API key is not configured (set OPENAI_API_KEY env var or "
                            + "paper-assistant.openai-api-key). The LLM-backed methods "
                            + "(answerRag, summarizePaper, survey) require it.");
        }
        return chatClient;
    }

    /**
     * Builds the ChatClient from Spring AI's auto-configured builder, only when
     * an API key is present — otherwise stores {@code null}.
     */
    private ChatClient buildChatClient(ObjectProvider<ChatClient.Builder> provider) {
        if (!StringUtils.hasText(config.openaiApiKey())) {
            log.warn("No OpenAI API key configured — LLM methods will be unavailable");
            return null;
        }
        ChatClient.Builder builder = provider.getIfAvailable();
        if (builder == null) {
            log.warn("ChatClient.Builder bean is not available (check spring-ai-openai dependency "
                    + "and api-key config) — LLM methods will be unavailable");
            return null;
        }
        return builder.build();
    }

    /** Persists a query record with input/output and hit count. */
    private void saveQueryHistory(String query, String answer, String lang,
                                  int hitCount, String ownerId) {
        try {
            QueryRecord record = QueryRecord.builder()
                    .queryText(query)
                    .answerText(answer)
                    .lang(lang != null ? lang : "zh")
                    .hitCount(hitCount)
                    .ownerId(ownerId != null ? ownerId : "")
                    .build();
            queryRecordRepository.save(record);
            log.debug("Query history saved: id={}", record.getId());
        } catch (Exception e) {
            log.warn("查询历史记录失败: {}", e.getMessage());
        }
    }

    /**
     * Extracts a compact source list from retrieval hits for the API response.
     * Each entry is {@code {"arxiv_id": ..., "title": ...}}.
     */
    private static List<Map<String, String>> extractSources(List<Map<String, Object>> hits) {
        List<Map<String, String>> sources = new ArrayList<>();
        for (Map<String, Object> hit : hits) {
            Map<String, String> src = new LinkedHashMap<>();
            src.put("arxiv_id", stringVal(hit.get("id")));

            @SuppressWarnings("unchecked")
            Map<String, Object> meta = (Map<String, Object>) hit.get("metadata");
            src.put("title", meta != null ? stringVal(meta.get("title")) : "");
            sources.add(src);
        }
        return sources;
    }

    /** Reads a paper's full text from its parsed JSON on disk. */
    private String extractPaperText(String arxivId) {
        Path jsonPath = Path.of(config.parsedDir(), arxivId + ".json");
        if (!Files.isRegularFile(jsonPath)) {
            return "";
        }
        try {
            JsonNode root = objectMapper.readTree(jsonPath.toFile());
            StringBuilder sb = new StringBuilder();
            JsonNode sections = root.get("sections");
            if (sections != null && sections.isArray()) {
                for (JsonNode sec : sections) {
                    appendSectionText(sb, sec);
                }
            }
            return sb.toString().trim();
        } catch (IOException e) {
            log.warn("Failed to read parsed JSON for {}: {}", arxivId, e.getMessage());
            return "";
        }
    }

    /** Recursively appends section + subsection content to the builder. */
    private static void appendSectionText(StringBuilder sb, JsonNode section) {
        String content = jsonString(section, "content").strip();
        if (!content.isEmpty()) {
            if (!sb.isEmpty()) {
                sb.append("\n\n");
            }
            sb.append(content);
        }
        JsonNode subs = section.get("subsections");
        if (subs != null && subs.isArray()) {
            for (JsonNode sub : subs) {
                String subContent = jsonString(sub, "content").strip();
                if (!subContent.isEmpty()) {
                    if (!sb.isEmpty()) {
                        sb.append("\n\n");
                    }
                    sb.append(subContent);
                }
            }
        }
    }

    /** Wraps a raw token in SSE {@code data: ...\n\n} format. */
    private static String sseEvent(String data) {
        return "data: " + data + "\n\n";
    }

    /** Safe JSON string extraction with null/empty default of "". */
    private static String jsonString(JsonNode node, String field) {
        if (node == null) {
            return "";
        }
        JsonNode value = node.get(field);
        if (value == null || value.isNull()) {
            return "";
        }
        return value.asText();
    }

    /** Safe object-to-string, defaulting to "". */
    private static String stringVal(Object value) {
        return value == null ? "" : value.toString();
    }

    /** Truncates a string for logging (avoids dumping huge queries). */
    private static String truncate(String s, int maxLen) {
        if (s == null) {
            return "";
        }
        return s.length() <= maxLen ? s : s.substring(0, maxLen);
    }

    /**
     * Cosine distance {@code 1 - cosine_similarity(a, b)} — the same metric as
     * PostgreSQL pgvector's {@code <=>} operator used by
     * {@link PaperRepository#findSimilarByEmbedding}. Handles any-dimensional
     * vectors and clamps the similarity to {@code [-1, 1]} to guard against
     * float rounding; a zero-norm vector is treated as maximally distant.
     */
    private static double cosineDistance(float[] a, float[] b) {
        int len = Math.min(a.length, b.length);
        double dot = 0.0;
        double normA = 0.0;
        double normB = 0.0;
        for (int i = 0; i < len; i++) {
            dot += (double) a[i] * b[i];
            normA += (double) a[i] * a[i];
            normB += (double) b[i] * b[i];
        }
        if (normA == 0.0 || normB == 0.0) {
            return 1.0;
        }
        double sim = dot / (Math.sqrt(normA) * Math.sqrt(normB));
        return 1.0 - Math.max(-1.0, Math.min(1.0, sim));
    }
}
