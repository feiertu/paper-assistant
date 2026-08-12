package com.paperassistant.controller;

import com.paperassistant.filter.OwnerFilter;
import com.paperassistant.repository.CitationRepository;
import com.paperassistant.service.CitationService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;

/**
 * Citation endpoints mirroring the Python citation graph / extraction / stats
 * functionality.
 *
 * <ul>
 *   <li>{@code GET /papers/{arxivId}/citations} — citation graph for one paper
 *       (cites + cited_by).</li>
 *   <li>{@code POST /citations/extract} — batch-extract citations from parsed
 *       JSON files and persist to the {@code citations} table.</li>
 *   <li>{@code GET /citations/stats} — aggregate citation statistics.</li>
 * </ul>
 *
 * <p>All blocking calls run on {@link Schedulers#boundedElastic()}.
 * Owner isolation uses {@link OwnerFilter#getOwnerId(ServerWebExchange)}.
 */
@RestController
public class CitationController {

    private static final Logger log = LoggerFactory.getLogger(CitationController.class);

    private static final Pattern ARXIV_ID_RE = Pattern.compile("[\\w.\\-]+");

    private final CitationService citationService;
    private final CitationRepository citationRepository;

    public CitationController(CitationService citationService,
                               CitationRepository citationRepository) {
        this.citationService = citationService;
        this.citationRepository = citationRepository;
    }

    /**
     * GET /papers/{arxivId}/citations — citation graph for one paper.
     *
     * <p>Returns the citing (outbound) and cited_by (inbound) relationships,
     * with each entry showing the linked arxiv_id, title, context snippet,
     * and whether the linked paper exists in the database.
     *
     * @param arxivId arXiv paper identifier
     * @return {@code {"arxiv_id", "cites": [...], "cited_by": [...]}}
     */
    @GetMapping("/papers/{arxivId}/citations")
    public Mono<Map<String, Object>> citations(@PathVariable String arxivId) {
        validateArxivId(arxivId);
        return Mono.fromCallable(() -> citationService.getGraph(arxivId))
                .subscribeOn(Schedulers.boundedElastic());
    }

    /**
     * POST /citations/extract — batch-extract citations from parsed JSON files.
     *
     * <p>Accepts an optional list of arxiv IDs to process; if omitted or empty,
     * all JSON files in {@code parsedDir} are processed.
     *
     * <p>Request body: {@code {"arxiv_ids": ["2301.12345", "2301.12346"]}}
     *
     * @param body JSON body with optional {@code arxiv_ids} array
     * @return {@code {"processed": N, "citations": M}}
     */
    @PostMapping("/citations/extract")
    public Mono<Map<String, Object>> extractCitations(@RequestBody Map<String, Object> body) {
        return Mono.fromCallable(() -> {
            @SuppressWarnings("unchecked")
            List<String> arxivIds = (List<String>) body.get("arxiv_ids");
            return citationService.batchExtract(arxivIds);
        }).subscribeOn(Schedulers.boundedElastic());
    }

    /**
     * GET /citations/stats — aggregate citation statistics.
     *
     * <p>Returns:
     * <ul>
     *   <li>{@code total_citations} — total number of citation edges</li>
     *   <li>{@code unique_citing} — number of distinct citing papers</li>
     *   <li>{@code unique_cited} — number of distinct cited papers</li>
     *   <li>{@code top_cited} — top 10 most-cited arXiv IDs with citation counts</li>
     *   <li>{@code top_citers} — top 10 papers that cite the most other papers</li>
     * </ul>
     */
    @GetMapping("/citations/stats")
    public Mono<Map<String, Object>> citationStats() {
        return Mono.fromCallable(() -> {
            long totalCitations = citationRepository.count();

            // Distinct counts via native SQL
            long uniqueCiting = citationRepository.countDistinctCiting();
            long uniqueCited = citationRepository.countDistinctCited();

            // Top cited papers (most inbound citations)
            List<Map<String, Object>> topCited = citationRepository.topCitedBy(10);

            // Top citing papers (most outbound citations)
            List<Map<String, Object>> topCiters = citationRepository.topCiters(10);

            Map<String, Object> result = new LinkedHashMap<>();
            result.put("total_citations", totalCitations);
            result.put("unique_citing", uniqueCiting);
            result.put("unique_cited", uniqueCited);
            result.put("top_cited", topCited);
            result.put("top_citers", topCiters);
            return result;
        }).subscribeOn(Schedulers.boundedElastic());
    }

    // ──────────────────────────────────────────────
    //  Private helpers
    // ──────────────────────────────────────────────

    /** Reject invalid arXiv IDs (path traversal / illegal chars). */
    private static void validateArxivId(String arxivId) {
        if (arxivId == null || arxivId.isBlank()
                || arxivId.contains("..")
                || arxivId.contains("/")
                || arxivId.contains("\\")
                || !ARXIV_ID_RE.matcher(arxivId).matches()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "无效的 arxiv_id: " + arxivId);
        }
    }
}
