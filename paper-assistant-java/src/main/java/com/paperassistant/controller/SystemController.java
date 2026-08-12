package com.paperassistant.controller;

import com.paperassistant.config.AppConfig;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.util.StringUtils;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;

import java.lang.reflect.RecordComponent;
import java.util.LinkedHashMap;
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
 * </ul>
 *
 * <p>The blocking JDBC probes in {@code /health/deep} run on the
 * {@link Schedulers#boundedElastic()} scheduler so the Netty event loop is not
 * blocked.
 */
@RestController
public class SystemController {

    private static final Logger log = LoggerFactory.getLogger(SystemController.class);

    private final AppConfig appConfig;
    private final JdbcTemplate jdbcTemplate;

    public SystemController(AppConfig appConfig, JdbcTemplate jdbcTemplate) {
        this.appConfig = appConfig;
        this.jdbcTemplate = jdbcTemplate;
    }

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
}
