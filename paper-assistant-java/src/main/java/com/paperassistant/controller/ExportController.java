package com.paperassistant.controller;

import com.paperassistant.entity.Paper;
import com.paperassistant.entity.QueryRecord;
import com.paperassistant.filter.OwnerFilter;
import com.paperassistant.repository.PaperRepository;
import com.paperassistant.repository.QueryRecordRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;

import java.time.format.DateTimeFormatter;
import java.util.List;
import java.util.Set;

/**
 * Export endpoints mirroring the Python export functionality.
 *
 * <ul>
 *   <li>{@code GET /export/papers?fmt=json|csv|bibtex&limit=200} — export papers
 *       for the current owner in the requested format.</li>
 *   <li>{@code GET /export/queries?fmt=json|csv&limit=500} — export query history
 *       for the current owner in the requested format.</li>
 * </ul>
 *
 * <p>All blocking JPA calls run on {@link Schedulers#boundedElastic()}.
 * Owner isolation uses {@link OwnerFilter#getOwnerId(ServerWebExchange)}.
 */
@RestController
public class ExportController {

    private static final Logger log = LoggerFactory.getLogger(ExportController.class);

    private static final DateTimeFormatter CREATED_AT_FORMAT =
            DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

    /** Valid export formats for papers, matched case-insensitively. */
    private static final Set<String> PAPER_FORMATS = Set.of("json", "csv", "bibtex");

    /** Valid export formats for queries, matched case-insensitively. */
    private static final Set<String> QUERY_FORMATS = Set.of("json", "csv");

    private final PaperRepository paperRepository;
    private final QueryRecordRepository queryRecordRepository;

    public ExportController(PaperRepository paperRepository,
                            QueryRecordRepository queryRecordRepository) {
        this.paperRepository = paperRepository;
        this.queryRecordRepository = queryRecordRepository;
    }

    /**
     * GET /export/papers — export current user's papers in json, csv, or bibtex.
     *
     * @param fmt     output format (json | csv | bibtex), case-insensitive, defaults to json
     * @param limit   max papers to export, capped at 2000, defaults to 200
     * @param exchange ServerWebExchange for owner isolation
     * @return a text response with appropriate Content-Type and Content-Disposition
     */
    @GetMapping("/export/papers")
    public Mono<ResponseEntity<String>> exportPapers(
            @RequestParam(defaultValue = "json") String fmt,
            @RequestParam(defaultValue = "200") int limit,
            ServerWebExchange exchange) {
        String ownerId = OwnerFilter.getOwnerId(exchange);
        return Mono.fromCallable(() -> {
            String resolvedFmt = (fmt != null ? fmt.trim().toLowerCase() : "json");
            if (!PAPER_FORMATS.contains(resolvedFmt)) {
                resolvedFmt = "json";
            }
            int lim = Math.min(2000, Math.max(1, limit));

            List<Paper> papers = paperRepository.findAllByOwnerId(
                    ownerId,
                    org.springframework.data.domain.PageRequest.of(0, lim));

            String body = switch (resolvedFmt) {
                case "csv" -> papersToCsv(papers);
                case "bibtex" -> papersToBibtex(papers);
                default -> papersToJson(papers);
            };

            String filename = "papers." + resolvedFmt;
            MediaType mediaType = MediaType.valueOf(
                    "csv".equals(resolvedFmt) ? "text/csv"
                    : "bibtex".equals(resolvedFmt) ? "text/plain"
                    : "application/json");

            log.info("Export papers: fmt={} count={} owner={}", resolvedFmt, papers.size(), ownerId);
            return ResponseEntity.ok()
                    .contentType(mediaType)
                    .header(HttpHeaders.CONTENT_DISPOSITION,
                            "attachment; filename=\"" + filename + "\"")
                    .body(body);
        }).subscribeOn(Schedulers.boundedElastic());
    }

    /**
     * GET /export/queries — export current user's query history in json or csv.
     *
     * @param fmt     output format (json | csv), case-insensitive, defaults to json
     * @param limit   max queries to export, capped at 2000, defaults to 500
     * @param exchange ServerWebExchange for owner isolation
     * @return a text response with appropriate Content-Type and Content-Disposition
     */
    @GetMapping("/export/queries")
    public Mono<ResponseEntity<String>> exportQueries(
            @RequestParam(defaultValue = "json") String fmt,
            @RequestParam(defaultValue = "500") int limit,
            ServerWebExchange exchange) {
        String ownerId = OwnerFilter.getOwnerId(exchange);
        return Mono.fromCallable(() -> {
            String resolvedFmt = (fmt != null ? fmt.trim().toLowerCase() : "json");
            if (!QUERY_FORMATS.contains(resolvedFmt)) {
                resolvedFmt = "json";
            }
            int lim = Math.min(2000, Math.max(1, limit));

            List<QueryRecord> queries = queryRecordRepository.findByOwnerIdOrderByCreatedAtDesc(ownerId);
            if (queries.size() > lim) {
                queries = queries.subList(0, lim);
            }

            String body = "csv".equals(resolvedFmt)
                    ? queriesToCsv(queries)
                    : queriesToJson(queries);

            String filename = "queries." + resolvedFmt;
            MediaType mediaType = "csv".equals(resolvedFmt)
                    ? MediaType.valueOf("text/csv")
                    : MediaType.APPLICATION_JSON;

            log.info("Export queries: fmt={} count={} owner={}", resolvedFmt, queries.size(), ownerId);
            return ResponseEntity.ok()
                    .contentType(mediaType)
                    .header(HttpHeaders.CONTENT_DISPOSITION,
                            "attachment; filename=\"" + filename + "\"")
                    .body(body);
        }).subscribeOn(Schedulers.boundedElastic());
    }

    // ──────────────────────────────────────────────
    //  Format converters — Papers
    // ──────────────────────────────────────────────

    /** Serialize papers as a compact JSON array of objects. */
    private static String papersToJson(List<Paper> papers) {
        StringBuilder sb = new StringBuilder();
        sb.append("[\n");
        for (int i = 0; i < papers.size(); i++) {
            if (i > 0) {
                sb.append(",\n");
            }
            sb.append(toPaperJson(papers.get(i)));
        }
        sb.append("\n]\n");
        return sb.toString();
    }

    /** Convert papers to CSV with header row. */
    private static String papersToCsv(List<Paper> papers) {
        StringBuilder sb = new StringBuilder();
        sb.append("arxiv_id,title,authors,abstract,published,pdf_url,source,ingest_status,chunk_count,owner_id,created_at\n");
        for (Paper p : papers) {
            sb.append(csvField(p.getArxivId())).append(',');
            sb.append(csvField(p.getTitle())).append(',');
            sb.append(csvField(p.getAuthors())).append(',');
            sb.append(csvField(p.getAbstractText())).append(',');
            sb.append(csvField(p.getPublished())).append(',');
            sb.append(csvField(p.getPdfUrl())).append(',');
            sb.append(csvField(p.getSource())).append(',');
            sb.append(csvField(p.getIngestStatus())).append(',');
            sb.append(p.getChunkCount() != null ? p.getChunkCount() : 0).append(',');
            sb.append(csvField(p.getOwnerId())).append(',');
            sb.append(p.getCreatedAt() != null ? p.getCreatedAt().format(CREATED_AT_FORMAT) : "").append('\n');
        }
        return sb.toString();
    }

    /** Convert papers to BibTeX entries. */
    private static String papersToBibtex(List<Paper> papers) {
        StringBuilder sb = new StringBuilder();
        for (Paper p : papers) {
            String key = "paper:" + (p.getArxivId() != null ? p.getArxivId() : p.getId());
            sb.append("@article{").append(key).append(",\n");
            sb.append("  title = {").append(bibtexValue(p.getTitle())).append("},\n");
            sb.append("  author = {").append(bibtexValue(p.getAuthors())).append("},\n");
            sb.append("  abstract = {").append(bibtexValue(p.getAbstractText())).append("},\n");
            String year = extractYear(p.getPublished());
            sb.append("  year = {").append(year).append("},\n");
            sb.append("  arxivId = {").append(bibtexValue(p.getArxivId())).append("},\n");
            sb.append("  url = {").append(bibtexValue(p.getPdfUrl())).append("}\n");
            sb.append("}\n\n");
        }
        return sb.toString();
    }

    // ──────────────────────────────────────────────
    //  Format converters — Queries
    // ──────────────────────────────────────────────

    /** Serialize queries as a compact JSON array. */
    private static String queriesToJson(List<QueryRecord> queries) {
        StringBuilder sb = new StringBuilder();
        sb.append("[\n");
        for (int i = 0; i < queries.size(); i++) {
            if (i > 0) {
                sb.append(",\n");
            }
            sb.append(toQueryJson(queries.get(i)));
        }
        sb.append("\n]\n");
        return sb.toString();
    }

    /** Convert queries to CSV with header row. */
    private static String queriesToCsv(List<QueryRecord> queries) {
        StringBuilder sb = new StringBuilder();
        sb.append("id,query_text,answer_text,lang,hit_count,owner_id,created_at\n");
        for (QueryRecord q : queries) {
            sb.append(q.getId() != null ? q.getId() : "").append(',');
            sb.append(csvField(q.getQueryText())).append(',');
            sb.append(csvField(q.getAnswerText())).append(',');
            sb.append(csvField(q.getLang())).append(',');
            sb.append(q.getHitCount() != null ? q.getHitCount() : 0).append(',');
            sb.append(csvField(q.getOwnerId())).append(',');
            sb.append(q.getCreatedAt() != null ? q.getCreatedAt().format(CREATED_AT_FORMAT) : "").append('\n');
        }
        return sb.toString();
    }

    // ──────────────────────────────────────────────
    //  JSON row helpers
    // ──────────────────────────────────────────────

    private static String toPaperJson(Paper p) {
        return "  {" +
                "\"id\":" + p.getId() + "," +
                "\"arxiv_id\":" + jsonString(p.getArxivId()) + "," +
                "\"title\":" + jsonString(p.getTitle()) + "," +
                "\"authors\":" + jsonString(p.getAuthors()) + "," +
                "\"abstract\":" + jsonString(p.getAbstractText()) + "," +
                "\"published\":" + jsonString(p.getPublished()) + "," +
                "\"pdf_url\":" + jsonString(p.getPdfUrl()) + "," +
                "\"source\":" + jsonString(p.getSource()) + "," +
                "\"ingest_status\":" + jsonString(p.getIngestStatus()) + "," +
                "\"chunk_count\":" + (p.getChunkCount() != null ? p.getChunkCount() : 0) + "," +
                "\"owner_id\":" + jsonString(p.getOwnerId()) + "," +
                "\"created_at\":" + jsonString(
                        p.getCreatedAt() != null ? p.getCreatedAt().format(CREATED_AT_FORMAT) : "") +
                "}";
    }

    private static String toQueryJson(QueryRecord q) {
        return "  {" +
                "\"id\":" + q.getId() + "," +
                "\"query_text\":" + jsonString(q.getQueryText()) + "," +
                "\"answer_text\":" + jsonString(q.getAnswerText()) + "," +
                "\"lang\":" + jsonString(q.getLang()) + "," +
                "\"hit_count\":" + (q.getHitCount() != null ? q.getHitCount() : 0) + "," +
                "\"owner_id\":" + jsonString(q.getOwnerId()) + "," +
                "\"created_at\":" + jsonString(
                        q.getCreatedAt() != null ? q.getCreatedAt().format(CREATED_AT_FORMAT) : "") +
                "}";
    }

    // ──────────────────────────────────────────────
    //  Value helpers
    // ──────────────────────────────────────────────

    /** JSON-encode a string: wrap in double quotes and escape backslashes/quotes. */
    private static String jsonString(String s) {
        if (s == null) {
            return "\"\"";
        }
        return "\"" + s.replace("\\", "\\\\")
                .replace("\"", "\\\"")
                .replace("\n", "\\n")
                .replace("\r", "\\r")
                .replace("\t", "\\t") + "\"";
    }

    /** Wrap a value in double-quotes and escape embedded quotes for CSV. */
    private static String csvField(String value) {
        if (value == null) {
            return "";
        }
        // If the value contains a comma, double-quote, or newline, wrap in quotes.
        if (value.indexOf(',') >= 0 || value.indexOf('"') >= 0 || value.indexOf('\n') >= 0) {
            return "\"" + value.replace("\"", "\"\"") + "\"";
        }
        return value;
    }

    /** Escape BibTeX special characters and wrap in braces (strip surrounding braces first). */
    private static String bibtexValue(String text) {
        if (text == null || text.isEmpty()) {
            return "";
        }
        String s = text;
        // Remove any existing leading/trailing braces to avoid double-wrapping.
        if (s.startsWith("{") && s.endsWith("}")) {
            s = s.substring(1, s.length() - 1);
        }
        // Escape remaining brace characters that belong to the text.
        s = s.replace("{", "\\{").replace("}", "\\}");
        return escapeBibtexChars(s);
    }

    /** Escape backslash and percent for BibTeX. */
    private static String escapeBibtexChars(String s) {
        return s.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("&", "\\&")
                .replace("#", "\\#")
                .replace("$", "\\$")
                .replace("_", "\\_")
                .replace("~", "\\~{}")
                .replace("^", "\\^{}");
    }

    /** Extract a 4-digit year from a date string like "2024-01-15" or "2024". */
    private static String extractYear(String published) {
        if (published == null || published.isBlank()) {
            return "";
        }
        // Try to find a 4-digit sequence.
        for (int i = 0; i <= published.length() - 4; i++) {
            if (Character.isDigit(published.charAt(i))
                    && Character.isDigit(published.charAt(i + 1))
                    && Character.isDigit(published.charAt(i + 2))
                    && Character.isDigit(published.charAt(i + 3))) {
                return published.substring(i, i + 4);
            }
        }
        return published;
    }
}
