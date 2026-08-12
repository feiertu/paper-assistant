package com.paperassistant.controller;

import com.github.benmanes.caffeine.cache.Cache;
import com.paperassistant.config.AppConfig;
import com.paperassistant.entity.Paper;
import com.paperassistant.entity.QueryRecord;
import com.paperassistant.filter.OwnerFilter;
import com.paperassistant.repository.PaperRepository;
import com.paperassistant.repository.QueryRecordRepository;
import com.paperassistant.service.EmbedService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.cache.CacheManager;
import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.util.StringUtils;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;

import java.lang.reflect.RecordComponent;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * System endpoints mirroring the Python {@code src/api/main.py}:
 *
 * <ul>
 *   <li>{@code GET /health} — shallow liveness check (Docker HEALTHCHECK);</li>
 *   <li>{@code GET /health/deep} — verifies DB connectivity, the pgvector
 *       extension and whether an LLM API key is configured;</li>
 *   <li>{@code GET /config} — a safe subset of {@link AppConfig}, excluding
 *       anything whose name hints at a secret.</li>
 *   <li>{@code GET /store/stats} — pgvector / paper table statistics;</li>
 *   <li>{@code GET /store/papers} — list ingested (vector-stored) papers;</li>
 *   <li>{@code DELETE /store/reset} — clear all vector data;</li>
 *   <li>{@code GET /cache/stats} — Caffeine cache hit/miss statistics;</li>
 *   <li>{@code DELETE /cache/clear?kind=all|llm|embed} — clear caches;</li>
 *   <li>{@code GET /queries?limit=20} — paginated query history;</li>
 *   <li>{@code DELETE /queries} — clear the current owner's query history.</li>
 * </ul>
 *
 * <p>Store backup/restore is deliberately omitted (out of scope for this task).
 *
 * <p>The blocking JDBC probes in {@code /health/deep} run on the
 * {@link Schedulers#boundedElastic()} scheduler so the Netty event loop is not
 * blocked.
 */
@RestController
public class SystemController {

    private static final Logger log = LoggerFactory.getLogger(SystemController.class);

    private static final DateTimeFormatter CREATED_AT_FORMAT =
            DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

    private final AppConfig appConfig;
    private final JdbcTemplate jdbcTemplate;
    private final PaperRepository paperRepository;
    private final QueryRecordRepository queryRecordRepository;
    private final EmbedService embedService;
    private final CacheManager cacheManager;

    public SystemController(AppConfig appConfig,
                            JdbcTemplate jdbcTemplate,
                            PaperRepository paperRepository,
                            QueryRecordRepository queryRecordRepository,
                            EmbedService embedService,
                            CacheManager cacheManager) {
        this.appConfig = appConfig;
        this.jdbcTemplate = jdbcTemplate;
        this.paperRepository = paperRepository;
        this.queryRecordRepository = queryRecordRepository;
        this.embedService = embedService;
        this.cacheManager = cacheManager;
    }

    // ──────────────────────────────────────────────
    //  Health & config (existing)
    // ──────────────────────────────────────────────

    @GetMapping("/health")
    public Mono<Map<String, String>> health() {
        return Mono.just(Map.of("status", "ok"));
    }

    @GetMapping("/config")
    public Mono<Map<String, Object>> config() {
        return Mono.fromSupplier(this::safeConfigSummary);
    }

    @GetMapping("/health/deep")
    public Mono<ResponseEntity<Map<String, Object>>> healthDeep() {
        return Mono.fromCallable(this::deepCheck).subscribeOn(Schedulers.boundedElastic());
    }

    /** Deep check: DB liveness, pgvector extension, LLM API key presence. */
    private ResponseEntity<Map<String, Object>> deepCheck() {
        Map<String, Object> checks = new LinkedHashMap<>();
        boolean healthy = true;

        // 1) Database connectivity
        try {
            jdbcTemplate.queryForObject("SELECT 1", Integer.class);
            checks.put("database", "ok");
        } catch (Exception e) {
            log.warn("Deep check: database unavailable: {}", safeMessage(e));
            checks.put("database", "error: " + safeMessage(e));
            healthy = false;
        }

        // 2) pgvector extension (only meaningful when the DB is reachable)
        if (healthy) {
            try {
                jdbcTemplate.queryForObject(
                        "SELECT 1 FROM pg_extension WHERE extname = 'vector'", Integer.class);
                checks.put("pgvector", "ok");
            } catch (EmptyResultDataAccessException e) {
                checks.put("pgvector", "error: pgvector extension 'vector' is not installed");
                healthy = false;
            } catch (Exception e) {
                checks.put("pgvector", "error: " + safeMessage(e));
                healthy = false;
            }
        } else {
            checks.put("pgvector", "skipped (database unavailable)");
        }

        // 3) LLM API key configured
        checks.put("llm_key_set", StringUtils.hasText(appConfig.openaiApiKey()));

        // 4) Embedding provider (mirrors the Python deep-check output)
        checks.put("embed_provider", appConfig.embeddingProvider());

        HttpStatus status = healthy ? HttpStatus.OK : HttpStatus.SERVICE_UNAVAILABLE;
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("status", healthy ? "healthy" : "degraded");
        body.put("checks", checks);
        return ResponseEntity.status(status).body(body);
    }

    // ──────────────────────────────────────────────
    //  Store (pgvector / papers)
    // ──────────────────────────────────────────────

    /**
     * GET /store/stats — vector store statistics.
     *
     * <p>Returns counts for total papers, ingested papers, pending papers,
     * papers with embeddings, and the total chunk count.
     */
    @GetMapping("/store/stats")
    public Mono<Map<String, Object>> storeStats() {
        return Mono.fromCallable(() -> {
            Map<String, Object> stats = new LinkedHashMap<>();
            Long tp = jdbcTemplate.queryForObject(
                    "SELECT COUNT(*) FROM papers", Long.class);
            Long ip = jdbcTemplate.queryForObject(
                    "SELECT COUNT(*) FROM papers WHERE ingest_status = 'ingested'", Long.class);
            Long pp = jdbcTemplate.queryForObject(
                    "SELECT COUNT(*) FROM papers WHERE ingest_status = 'pending'", Long.class);
            Long pwe = jdbcTemplate.queryForObject(
                    "SELECT COUNT(*) FROM papers WHERE embedding IS NOT NULL", Long.class);
            Long tc = jdbcTemplate.queryForObject(
                    "SELECT COALESCE(SUM(chunk_count), 0) FROM papers", Long.class);

            stats.put("total_papers", tp != null ? tp : 0L);
            stats.put("ingested_papers", ip != null ? ip : 0L);
            stats.put("pending_papers", pp != null ? pp : 0L);
            stats.put("papers_with_embedding", pwe != null ? pwe : 0L);
            stats.put("total_chunks", tc != null ? tc : 0L);
            return stats;
        }).subscribeOn(Schedulers.boundedElastic());
    }

    /**
     * GET /store/papers — list ingested (vector-stored) papers.
     *
     * <p>Returns arxiv_id, title, chunk_count for each paper that has been
     * ingested into the vector store. Paginated via limit/offset.
     */
    @GetMapping("/store/papers")
    public Mono<Map<String, Object>> storePapers(
            @RequestParam(defaultValue = "50") int limit,
            @RequestParam(defaultValue = "0") int offset,
            ServerWebExchange exchange) {
        String ownerId = OwnerFilter.getOwnerId(exchange);
        return Mono.fromCallable(() -> {
            int lim = Math.min(500, Math.max(1, limit));
            int off = Math.max(0, offset);

            List<Paper> papers = paperRepository.findIngestedByOwnerId(ownerId);
            long total = papers.size();

            List<Map<String, Object>> items = new ArrayList<>();
            int to = Math.min(off + lim, papers.size());
            for (int i = off; i < to; i++) {
                Paper p = papers.get(i);
                Map<String, Object> item = new LinkedHashMap<>();
                item.put("arxiv_id", nvl(p.getArxivId()));
                item.put("title", nvl(p.getTitle()));
                item.put("chunk_count", p.getChunkCount() != null ? p.getChunkCount() : 0);
                item.put("ingest_status", nvl(p.getIngestStatus()));
                item.put("created_at", p.getCreatedAt() != null
                        ? p.getCreatedAt().format(CREATED_AT_FORMAT) : "");
                items.add(item);
            }

            Map<String, Object> result = new LinkedHashMap<>();
            result.put("papers", items);
            result.put("total", total);
            return result;
        }).subscribeOn(Schedulers.boundedElastic());
    }

    /**
     * DELETE /store/reset — clear all vector data (papers + embeddings).
     *
     * <p>This deletes all papers in the database for the current owner.
     * Use with caution; there is no undo.
     */
    @DeleteMapping("/store/reset")
    public Mono<Map<String, Object>> storeReset(ServerWebExchange exchange) {
        String ownerId = OwnerFilter.getOwnerId(exchange);
        return Mono.fromCallable(() -> {
            long deleted = jdbcTemplate.update(
                    "DELETE FROM papers WHERE owner_id = ?", ownerId);
            log.warn("Store reset: owner={} deleted_papers={}", ownerId, deleted);
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("status", "ok");
            result.put("deleted", deleted);
            return result;
        }).subscribeOn(Schedulers.boundedElastic());
    }

    // ──────────────────────────────────────────────
    //  Cache (Caffeine)
    // ──────────────────────────────────────────────

    /**
     * GET /cache/stats — Caffeine cache statistics.
     *
     * <p>Returns stats for both the LLM cache (via Spring CacheManager)
     * and the Embedding cache (via EmbedService's Caffeine cache),
     * including approximate size, hit/miss counts, and eviction counts.
     */
    @GetMapping("/cache/stats")
    public Mono<Map<String, Object>> cacheStats() {
        return Mono.fromCallable(() -> {
            Map<String, Object> result = new LinkedHashMap<>();

            // LLM cache (Spring CacheManager)
            org.springframework.cache.Cache llmCache = cacheManager.getCache("llmCache");
            Map<String, Object> llm = new LinkedHashMap<>();
            if (llmCache != null) {
                Object nativeCache = llmCache.getNativeCache();
                llm.put("type", nativeCache != null ? nativeCache.getClass().getSimpleName() : "unknown");
                // Caffeine-specific stats via reflection (safe because we know it's Caffeine)
                if (nativeCache instanceof com.github.benmanes.caffeine.cache.Cache<?, ?> c) {
                    llm.put("estimated_size", c.estimatedSize());
                    llm.put("stats", c.stats().toString());
                }
            } else {
                llm.put("type", "unavailable");
            }
            result.put("llm_cache", llm);

            // Embed cache (direct Caffeine cache in EmbedService)
            Cache<String, float[]> embedCache = embedService.getEmbedCache();
            Map<String, Object> embed = new LinkedHashMap<>();
            embed.put("type", "Caffeine");
            embed.put("enabled", embedService.isEmbedCacheEnabled());
            embed.put("estimated_size", embedCache.estimatedSize());
            embed.put("stats", embedCache.stats().toString());
            result.put("embed_cache", embed);

            return result;
        }).subscribeOn(Schedulers.boundedElastic());
    }

    /**
     * DELETE /cache/clear?kind=all|llm|embed — clear specified caches.
     *
     * <p>{@code kind=all} clears both caches; {@code kind=llm} clears only the
     * LLM cache; {@code kind=embed} clears only the embedding cache.
     * Defaults to {@code all} when the parameter is omitted or unrecognized.
     */
    @DeleteMapping("/cache/clear")
    public Mono<Map<String, Object>> cacheClear(
            @RequestParam(defaultValue = "all") String kind) {
        return Mono.fromCallable(() -> {
            Map<String, Object> result = new LinkedHashMap<>();
            String resolved = kind != null ? kind.toLowerCase().trim() : "all";
            boolean clearLlm = "all".equals(resolved) || "llm".equals(resolved);
            boolean clearEmbed = "all".equals(resolved) || "embed".equals(resolved);

            // Clear LLM cache
            if (clearLlm) {
                org.springframework.cache.Cache llmCache = cacheManager.getCache("llmCache");
                if (llmCache != null) {
                    llmCache.clear();
                    result.put("llm_cache", "cleared");
                    log.info("Cache clear: LLM cache cleared");
                } else {
                    result.put("llm_cache", "unavailable");
                }
            }

            // Clear embed cache
            if (clearEmbed) {
                embedService.getEmbedCache().invalidateAll();
                result.put("embed_cache", "cleared");
                log.info("Cache clear: embed cache cleared");
            }

            result.put("kind", resolved);
            result.put("status", "ok");
            return result;
        }).subscribeOn(Schedulers.boundedElastic());
    }

    // ──────────────────────────────────────────────
    //  Query history
    // ──────────────────────────────────────────────

    /**
     * GET /queries?limit=20 — paginated query history for the current owner.
     *
     * <p>Returns the most recent queries ordered by created_at DESC.
     */
    @GetMapping("/queries")
    public Mono<Map<String, Object>> queryHistory(
            @RequestParam(defaultValue = "20") int limit,
            ServerWebExchange exchange) {
        String ownerId = OwnerFilter.getOwnerId(exchange);
        return Mono.fromCallable(() -> {
            int lim = Math.min(200, Math.max(1, limit));
            List<QueryRecord> queries = queryRecordRepository
                    .findByOwnerIdOrderByCreatedAtDesc(ownerId);
            if (queries.size() > lim) {
                queries = queries.subList(0, lim);
            }

            List<Map<String, Object>> items = new ArrayList<>(queries.size());
            for (QueryRecord q : queries) {
                Map<String, Object> item = new LinkedHashMap<>();
                item.put("id", q.getId());
                item.put("query_text", nvl(q.getQueryText()));
                item.put("answer_text", nvl(q.getAnswerText()));
                item.put("lang", nvl(q.getLang()));
                item.put("hit_count", q.getHitCount() != null ? q.getHitCount() : 0);
                item.put("owner_id", nvl(q.getOwnerId()));
                item.put("created_at", q.getCreatedAt() != null
                        ? q.getCreatedAt().format(CREATED_AT_FORMAT) : "");
                items.add(item);
            }

            Map<String, Object> result = new LinkedHashMap<>();
            result.put("queries", items);
            result.put("total", queryRecordRepository.countByOwnerId(ownerId));
            return result;
        }).subscribeOn(Schedulers.boundedElastic());
    }

    /**
     * DELETE /queries — delete all query history for the current owner.
     */
    @DeleteMapping("/queries")
    public Mono<Map<String, Object>> clearQueryHistory(ServerWebExchange exchange) {
        String ownerId = OwnerFilter.getOwnerId(exchange);
        return Mono.fromCallable(() -> {
            queryRecordRepository.deleteByOwnerId(ownerId);
            log.info("Query history cleared: owner={}", ownerId);
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("status", "ok");
            result.put("owner_id", ownerId);
            return result;
        }).subscribeOn(Schedulers.boundedElastic());
    }

    // ──────────────────────────────────────────────
    //  Config helpers (existing)
    // ──────────────────────────────────────────────

    /**
     * Builds an ordered config summary from every {@link AppConfig} record
     * component whose name does not look sensitive, and renames keys to
     * snake_case. Secrets (anything containing {@code key}, {@code secret},
     * {@code password} or {@code token}) plus {@code sessionCookie} and
     * {@code apiCorsOrigins} are excluded.
     */
    private Map<String, Object> safeConfigSummary() {
        Map<String, Object> summary = new LinkedHashMap<>();
        for (RecordComponent component : AppConfig.class.getRecordComponents()) {
            String name = component.getName();
            if (isSensitive(name)) {
                continue;
            }
            try {
                summary.put(toSnakeCase(name), component.getAccessor().invoke(appConfig));
            } catch (ReflectiveOperationException e) {
                log.warn("Config summary: could not read {}: {}", name, e.getMessage());
            }
        }
        return summary;
    }

    private static boolean isSensitive(String name) {
        String lower = name.toLowerCase();
        return lower.contains("key")
                || lower.contains("secret")
                || lower.contains("password")
                || lower.contains("token")
                || "sessionCookie".equals(name)
                || "apiCorsOrigins".equals(name);
    }

    private static String toSnakeCase(String camel) {
        StringBuilder sb = new StringBuilder(camel.length() + 8);
        for (int i = 0; i < camel.length(); i++) {
            char c = camel.charAt(i);
            if (Character.isUpperCase(c)) {
                if (i > 0) {
                    sb.append('_');
                }
                sb.append(Character.toLowerCase(c));
            } else {
                sb.append(c);
            }
        }
        return sb.toString();
    }

    private static String safeMessage(Exception e) {
        return e.getMessage() != null ? e.getMessage() : e.getClass().getSimpleName();
    }

    private static String nvl(String s) {
        return s == null ? "" : s;
    }
}
