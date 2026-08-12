package com.paperassistant.service;

import com.github.benmanes.caffeine.cache.Cache;
import com.github.benmanes.caffeine.cache.Caffeine;
import com.paperassistant.config.AppConfig;
import com.paperassistant.entity.Paper;
import com.paperassistant.repository.PaperRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.embedding.Embedding;
import org.springframework.ai.embedding.EmbeddingResponse;
import org.springframework.ai.openai.OpenAiEmbeddingModel;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientResponseException;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * Text embedding service mirroring the Python {@code src/embed/embedding.py}.
 *
 * <p>Supports three backends, selectable via the comma-separated
 * {@code paper-assistant.embedding-provider} setting:
 *
 * <ul>
 *   <li>{@code openai} — Spring AI {@link OpenAiEmbeddingModel} (the auto-configured
 *       bean, absent when no OpenAI API key is set);</li>
 *   <li>{@code voyage} — raw {@link WebClient} call to
 *       {@code https://api.voyageai.com/v1/embeddings} with a Bearer token;</li>
 *   <li>{@code local} — TODO (Python uses sentence-transformers; not ported yet).</li>
 * </ul>
 *
 * <p>Every backend emits L2-normalized {@code float[]} vectors of
 * {@link AppConfig#embeddingDim()} length so that cosine similarity can be used
 * directly, and results are memoized in a Caffeine cache keyed by
 * {@code SHA-256(provider|text)} with size/TTL from
 * {@code cacheEmbedMaxsize} / {@code cacheEmbedTtl} (matches Python's
 * {@code make_embed_key()} + {@code CACHE_EMBED_*}). When
 * {@code cacheEnabled} is {@code false} the cache is bypassed entirely.
 */
@Service
public class EmbedService {

    private static final Logger log = LoggerFactory.getLogger(EmbedService.class);

    /** Voyage embeddings endpoint (see {@link #VOYAGE_MODEL}). */
    private static final String VOYAGE_BASE_URL = "https://api.voyageai.com";
    private static final String VOYAGE_PATH = "/v1/embeddings";
    /** Voyage document-embedding model (brief Step 3). */
    private static final String VOYAGE_MODEL = "voyage-3";
    /** "document" vs "query" input type on the Voyage API. */
    private static final String VOYAGE_INPUT_TYPE = "document";
    private static final Duration VOYAGE_TIMEOUT = Duration.ofSeconds(60);

    private final AppConfig config;
    /** Nullable: only present when Spring AI creates the OpenAI embedding bean. */
    private final OpenAiEmbeddingModel openAiEmbeddingModel;
    private final WebClient voyageWebClient;
    private final List<String> providers;
    private final Cache<String, float[]> cache;
    private final boolean cacheEnabled;
    /** BM25 sparse retrieval (used by RRF / hybrid retrieval). */
    private final Bm25Service bm25Service;
    /** pgvector dense retrieval (used by RRF / hybrid retrieval). */
    private final PaperRepository paperRepository;

    /**
     * {@code openAiEmbeddingModel} is resolved through an {@link ObjectProvider}
     * so it is optional — when the {@code spring.ai.openai.api-key} property is
     * blank Spring AI does not register the bean and {@code getIfAvailable()}
     * yields {@code null}.
     */
    public EmbedService(AppConfig config,
                        ObjectProvider<OpenAiEmbeddingModel> openAiEmbeddingModelProvider,
                        WebClient.Builder webClientBuilder,
                        Bm25Service bm25Service,
                        PaperRepository paperRepository) {
        this.config = config;
        this.openAiEmbeddingModel = openAiEmbeddingModelProvider.getIfAvailable();
        this.voyageWebClient = webClientBuilder.baseUrl(VOYAGE_BASE_URL).build();
        this.providers = parseProviders(config.embeddingProvider());
        this.cacheEnabled = Boolean.TRUE.equals(config.cacheEnabled());
        this.cache = Caffeine.newBuilder()
                .maximumSize(Math.max(0, config.cacheEmbedMaxsize()))
                .expireAfterWrite(Duration.ofSeconds(Math.max(1, config.cacheEmbedTtl())))
                .build();
        this.bm25Service = bm25Service;
        this.paperRepository = paperRepository;
        log.info("EmbedService initialized: providers={} model={} dim={} cache={} openai={}",
                providers, config.embeddingModel(), config.embeddingDim(),
                cacheEnabled ? "enabled" : "disabled",
                openAiEmbeddingModel != null ? "available" : "absent");
    }

    // ---------- Public API (mirrors Python Embedder) ----------

    /**
     * Returns the raw Caffeine embedding cache so that controllers (e.g.
     * {@code SystemController}) can report hit/miss stats and clear it on demand.
     */
    public Cache<String, float[]> getEmbedCache() {
        return cache;
    }

    /** Whether the embedding cache is currently enabled. */
    public boolean isEmbedCacheEnabled() {
        return cacheEnabled;
    }

    /**
     * Embed a list of texts using the first configured provider, with per-text
     * cache lookup and in-order merging. Empty input yields an empty list.
     */
    public List<float[]> embed(List<String> texts) {
        if (texts == null || texts.isEmpty()) {
            return List.of();
        }
        if (providers.isEmpty()) {
            throw new IllegalStateException(
                    "No embedding providers configured (paper-assistant.embedding-provider is blank)");
        }
        return embedWithCache(texts, providers.get(0));
    }

    /** Single-text convenience wrapper around {@link #embed(List)}. */
    public float[] embedQuery(String text) {
        return embed(List.of(text)).get(0);
    }

    /** Embed a list of texts with every configured provider, keyed by provider name. */
    public Map<String, List<float[]>> embedAll(List<String> texts) {
        Map<String, List<float[]>> result = new LinkedHashMap<>();
        if (texts == null || texts.isEmpty()) {
            for (String provider : providers) {
                result.put(provider, List.of());
            }
            return result;
        }
        for (String provider : providers) {
            result.put(provider, embedWithCache(texts, provider));
        }
        return result;
    }

    /** The configured provider names, in order (for RRF / hybrid retrieval). */
    public List<String> providers() {
        return providers;
    }

    /** The configured embedding dimensionality. */
    public int dim() {
        return config.embeddingDim();
    }

    // ---------- Hybrid retrieval (RRF fusion) ----------

    /**
     * Reciprocal Rank Fusion over the two retrieval paths:
     *
     * <ol>
     *   <li><b>dense</b> — {@code embedQuery(query)} → pgvector
     *       {@code <=>} query via {@link PaperRepository#findSimilarByEmbedding};</li>
     *   <li><b>BM25</b> — {@link Bm25Service#search} sparse retrieval.</li>
     * </ol>
     *
     * <p>Each path contributes its top {@code rrfTopN} ranked hits, fused with
     * {@code weight / (rrfK + rank)} (rank 1-indexed). Dense weight = {@code 1 - bm25Weight},
     * BM25 weight = {@code bm25Weight} (config, default 0.3). Results are sorted by
     * RRF score descending and trimmed to {@code topK}; every hit carries an
     * {@code rrf_score} field (mirrors Python {@code hybrid_retrieve()}).
     *
     * @param query   search text
     * @param topK    max results to return
     * @param ownerId multi-user isolation filter for the pgvector query
     */
    public List<Map<String, Object>> rrfRerank(String query, int topK, String ownerId) {
        return fuseRrf(query, topK, ownerId);
    }

    /**
     * Hybrid retrieval pipeline: dense + BM25 → RRF fusion → (optional
     * Cross-Encoder re-ranking) → top-K.
     *
     * <p>Currently identical to {@link #rrfRerank}: the Cross-Encoder step is a
     * TODO (DJL/ONNX needs separate handling, as in Python's
     * {@code src/embed/reranker.py}), so the RRF-fused result is returned as-is.
     */
    public List<Map<String, Object>> hybridRetrieve(String query, int topK, String ownerId) {
        // TODO(Cross-Encoder): after RRF fusion, re-rank fused_hits with a
        // Cross-Encoder when len(fused) > topK (mirrors Python hybrid_retrieve
        // Step 4). DJL/ONNX model hosting is deferred to a later task.
        return fuseRrf(query, topK, ownerId);
    }

    /**
     * Dense + BM25 retrieval → RRF fusion → top-K.
     *
     * <p>Result maps mirror Python {@code hybrid_retrieve()} output: keys
     * {@code id}, {@code document}, {@code metadata}, {@code rrf_score}, plus a
     * unified {@code score} (RRF score when the path has no native score) and a
     * {@code distance} compatibility field derived from {@code score}.
     */
    private List<Map<String, Object>> fuseRrf(String query, int topK, String ownerId) {
        if (query == null || query.isBlank() || topK <= 0) {
            return List.of();
        }
        int rrfTopN = Math.max(1, config.rrfTopN());
        int rrfK = Math.max(1, config.rrfK());
        double bm25Weight = config.bm25Weight();
        double denseWeight = 1.0 - bm25Weight;

        // 1) Dense retrieval: query embedding → pgvector similarity.
        float[] queryEmbedding = embedQuery(query);
        // Arrays.toString(float[]) yields "[0.1, 0.2, ...]" — the pgvector literal format.
        List<Paper> densePapers = paperRepository.findSimilarByEmbedding(
                Arrays.toString(queryEmbedding), ownerId, rrfTopN);

        // 2) BM25 sparse retrieval.
        List<Bm25Hit> bm25Hits = bm25Service.search(query, rrfTopN);

        // 3) RRF fusion: score = weight / (rrfK + rank), rank 1-indexed.
        Map<String, Double> rrfScores = new HashMap<>();
        Map<String, Map<String, Object>> hitMap = new LinkedHashMap<>();

        for (int rank = 0; rank < densePapers.size(); rank++) {
            Paper p = densePapers.get(rank);
            String id = p.getArxivId();
            rrfScores.merge(id, denseWeight / (rrfK + rank + 1), Double::sum);
            hitMap.putIfAbsent(id, toDenseHit(p));
        }
        for (int rank = 0; rank < bm25Hits.size(); rank++) {
            Bm25Hit hit = bm25Hits.get(rank);
            rrfScores.merge(hit.id(), bm25Weight / (rrfK + rank + 1), Double::sum);
            hitMap.putIfAbsent(hit.id(), toBm25Hit(hit));
        }

        // 4) Sort by RRF score descending, keep the top-K. When both paths return
        //    the same id, the dense hit is kept (Python keeps the first path).
        List<Map.Entry<String, Double>> sorted = new ArrayList<>(rrfScores.entrySet());
        sorted.sort(Map.Entry.<String, Double>comparingByValue().reversed());

        List<Map<String, Object>> results = new ArrayList<>(Math.min(topK, sorted.size()));
        for (Map.Entry<String, Double> entry : sorted) {
            if (results.size() >= topK) {
                break;
            }
            Map<String, Object> hit = new LinkedHashMap<>(hitMap.get(entry.getKey()));
            double rrfScore = Math.round(entry.getValue() * 1_000_000.0) / 1_000_000.0;
            hit.put("rrf_score", rrfScore);
            // Unify the score field: dense hits have no native score here (the
            // distance column is not mapped onto Paper), so fall back to rrf_score.
            if (!hit.containsKey("score")) {
                hit.put("score", rrfScore);
            }
            // Python hybrid_retrieve keeps a distance field for old-code compat.
            if (!hit.containsKey("distance")) {
                double score = hit.get("score") instanceof Number n ? n.doubleValue() : 0.0;
                hit.put("distance", score != 0.0 ? 1.0 / (1.0 + score) : 0.0);
            }
            results.add(hit);
        }
        return results;
    }

    /** Dense hit shape: {@code {id, document, metadata}} (id = paper arxivId). */
    private static Map<String, Object> toDenseHit(Paper paper) {
        Map<String, Object> hit = new LinkedHashMap<>();
        hit.put("id", paper.getArxivId());
        hit.put("document", documentText(paper));
        Map<String, Object> metadata = new LinkedHashMap<>();
        metadata.put("paper_id", paper.getId());
        hit.put("metadata", metadata);
        return hit;
    }

    /** BM25 hit shape: {@code {id, document, metadata, score}}. */
    private static Map<String, Object> toBm25Hit(Bm25Hit hit) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("id", hit.id());
        map.put("document", hit.document());
        map.put("metadata", hit.metadata());
        map.put("score", hit.score());
        return map;
    }

    /** Document text for a paper: abstract, falling back to the title. */
    private static String documentText(Paper paper) {
        String text = paper.getAbstractText();
        if (!StringUtils.hasText(text)) {
            text = paper.getTitle();
        }
        return text == null ? "" : text;
    }

    // ---------- Cache-aware embedding (mirrors _embed_with_cache) ----------

    private List<float[]> embedWithCache(List<String> texts, String provider) {
        // 1) cache lookup per text
        Map<Integer, float[]> cachedVecs = new HashMap<>();
        List<Integer> uncachedIndices = new ArrayList<>();
        List<String> uncachedTexts = new ArrayList<>();

        for (int i = 0; i < texts.size(); i++) {
            float[] vec = cacheEnabled ? cache.getIfPresent(makeEmbedKey(texts.get(i), provider)) : null;
            if (vec != null) {
                cachedVecs.put(i, vec);
            } else {
                uncachedIndices.add(i);
                uncachedTexts.add(texts.get(i));
            }
        }

        // 2) all hit — merge cached entries and return
        if (uncachedTexts.isEmpty()) {
            log.debug("Embedding cache fully hit: {}/{} ({})", texts.size(), texts.size(), provider);
            return mergeResult(texts.size(), cachedVecs, uncachedIndices, List.of());
        }

        // 3) call the backend for the miss set
        log.info("Embedding: {} cached, {} via API ({})", cachedVecs.size(), uncachedTexts.size(), provider);
        List<float[]> newVecs = embedByProvider(uncachedTexts, provider);
        if (newVecs.size() != uncachedTexts.size()) {
            throw new IllegalStateException(
                    "Provider '" + provider + "' returned " + newVecs.size()
                            + " vectors for " + uncachedTexts.size() + " texts");
        }

        // 4) write cache
        if (cacheEnabled) {
            for (int j = 0; j < uncachedTexts.size(); j++) {
                cache.put(makeEmbedKey(uncachedTexts.get(j), provider), newVecs.get(j));
            }
        }

        // 5) merge in original order
        return mergeResult(texts.size(), cachedVecs, uncachedIndices, newVecs);
    }

    /** Builds a list with every index populated: cached entries plus fresh vectors. */
    private static List<float[]> mergeResult(int size, Map<Integer, float[]> cachedVecs,
                                             List<Integer> uncachedIndices, List<float[]> newVecs) {
        List<float[]> result = new ArrayList<>(size);
        for (int i = 0; i < size; i++) {
            result.add(null);
        }
        for (Map.Entry<Integer, float[]> e : cachedVecs.entrySet()) {
            result.set(e.getKey(), e.getValue());
        }
        for (int j = 0; j < uncachedIndices.size(); j++) {
            result.set(uncachedIndices.get(j), newVecs.get(j));
        }
        return result;
    }

    // ---------- Backend dispatch ----------

    private List<float[]> embedByProvider(List<String> texts, String provider) {
        return switch (provider) {
            case "openai" -> embedOpenAi(texts);
            case "voyage" -> embedVoyage(texts);
            case "local" -> throw new UnsupportedOperationException(
                    "Local embedding backend is not implemented yet in the Java rewrite");
            default -> throw new IllegalArgumentException("Unknown embedding provider: " + provider);
        };
    }

    // ---------- OpenAI backend (Spring AI) ----------

    private List<float[]> embedOpenAi(List<String> texts) {
        if (openAiEmbeddingModel == null) {
            throw new IllegalStateException(
                    "OpenAI embedding backend requested but OpenAiEmbeddingModel bean is unavailable "
                            + "(set spring.ai.openai.api-key / OPENAI_API_KEY)");
        }
        EmbeddingResponse response = openAiEmbeddingModel.embedForResponse(texts);
        int expectedDim = config.embeddingDim();
        List<float[]> vectors = new ArrayList<>(response.getResults().size());
        for (Embedding embedding : response.getResults()) {
            float[] output = embedding.getOutput();
            if (output.length != expectedDim) {
                throw new IllegalStateException(
                        "OpenAI embedding returned " + output.length + "-dim vector, expected "
                                + expectedDim + " (paper-assistant.embedding-dim). "
                                + "Ensure spring.ai.openai.embedding.options.dimensions is set "
                                + "so pgvector vector(" + expectedDim + ") stays consistent");
            }
            vectors.add(l2Normalize(output));
        }
        return vectors;
    }

    // ---------- Voyage backend (WebClient) ----------

    private List<float[]> embedVoyage(List<String> texts) {
        String apiKey = config.voyageApiKey();
        if (!StringUtils.hasText(apiKey)) {
            throw new IllegalStateException(
                    "Voyage embedding backend requested but voyageApiKey is not configured");
        }
        VoyageRequest body = new VoyageRequest(VOYAGE_MODEL, texts, VOYAGE_INPUT_TYPE);
        VoyageResponse response;
        try {
            response = voyageWebClient.post()
                    .uri(VOYAGE_PATH)
                    .header(HttpHeaders.AUTHORIZATION, "Bearer " + apiKey)
                    .contentType(MediaType.APPLICATION_JSON)
                    .bodyValue(body)
                    .retrieve()
                    .bodyToMono(VoyageResponse.class)
                    .block(VOYAGE_TIMEOUT);
        } catch (WebClientResponseException e) {
            throw new IllegalStateException(
                    "Voyage embedding API returned " + e.getStatusCode().value()
                            + ": " + safeMessage(e), e);
        }
        if (response == null || response.data() == null || response.data().size() != texts.size()) {
            throw new IllegalStateException(
                    "Voyage embedding API returned an unexpected response ("
                            + (response == null || response.data() == null ? 0 : response.data().size())
                            + " vectors for " + texts.size() + " texts)");
        }
        List<float[]> vectors = new ArrayList<>(response.data().size());
        for (VoyageEmbedding e : response.data()) {
            vectors.add(l2Normalize(toFloats(e.embedding())));
        }
        return vectors;
    }

    // ---------- Shared helpers ----------

    /**
     * L2-normalizes a vector in place-free fashion: divides every element by the
     * Euclidean norm of the vector. A zero vector (norm 0) is returned unchanged,
     * matching the Python {@code norms[norms == 0] = 1.0} guard.
     */
    static float[] l2Normalize(float[] vec) {
        double sum = 0.0;
        for (float v : vec) {
            sum += (double) v * v;
        }
        if (sum == 0.0) {
            // Return a copy, never the caller's reference, so cache contents
            // cannot be mutated through a returned zero vector.
            return vec.clone();
        }
        double norm = Math.sqrt(sum);
        float[] out = new float[vec.length];
        for (int i = 0; i < vec.length; i++) {
            out[i] = (float) (vec[i] / norm);
        }
        return out;
    }

    /** Cache key: {@code SHA-256(provider|text)} — same shape as Python {@code make_embed_key()}. */
    private static String makeEmbedKey(String text, String provider) {
        return sha256(provider + "|" + text);
    }

    private static String sha256(String input) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] bytes = digest.digest(input.getBytes(StandardCharsets.UTF_8));
            StringBuilder hex = new StringBuilder(bytes.length * 2);
            for (byte b : bytes) {
                hex.append(Character.forDigit((b >> 4) & 0xf, 16));
                hex.append(Character.forDigit(b & 0xf, 16));
            }
            return hex.toString();
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 algorithm unavailable", e);
        }
    }

    private static List<String> parseProviders(String raw) {
        List<String> providers = new ArrayList<>();
        if (raw == null) {
            return providers;
        }
        for (String part : raw.split(",")) {
            String p = part.trim().toLowerCase(Locale.ROOT);
            if (!p.isEmpty() && !providers.contains(p)) {
                providers.add(p);
            }
        }
        return providers;
    }

    private static float[] toFloats(List<Double> values) {
        float[] out = new float[values.size()];
        for (int i = 0; i < values.size(); i++) {
            out[i] = values.get(i).floatValue();
        }
        return out;
    }

    private static String safeMessage(Throwable t) {
        return t.getMessage() != null ? t.getMessage() : t.getClass().getSimpleName();
    }

    // ---------- Voyage API DTOs (Jackson) ----------

    /** Request body: {@code {"model": "voyage-3", "input": [...], "input_type": "document"}}. */
    private record VoyageRequest(String model, List<String> input, String input_type) {
    }

    /** Response body: {@code {"object": "list", "data": [{"embedding": [...]}], ...}}. */
    private record VoyageResponse(List<VoyageEmbedding> data) {
    }

    private record VoyageEmbedding(List<Double> embedding) {
    }
}
