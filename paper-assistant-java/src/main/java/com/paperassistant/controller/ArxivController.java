package com.paperassistant.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.paperassistant.config.AppConfig;
import com.paperassistant.dto.request.ArxivFetchRequest;
import com.paperassistant.dto.request.ArxivPipelineRequest;
import com.paperassistant.entity.FetchHistory;
import com.paperassistant.entity.Paper;
import com.paperassistant.filter.OwnerFilter;
import com.paperassistant.repository.FetchHistoryRepository;
import com.paperassistant.repository.PaperRepository;
import com.paperassistant.service.FetchResult;
import com.paperassistant.service.FetchService;
import com.paperassistant.service.ParseService;
import com.paperassistant.service.RagService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.util.StringUtils;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * arXiv 抓取管道端点 — Python {@code src/api/main.py} 的 {@code /arxiv/*} 与
 * {@code /fetch/history*} 路由族。
 *
 * <ul>
 *   <li>{@code POST /arxiv/fetch} — 搜索并保存元数据；</li>
 *   <li>{@code POST /arxiv/download} — 下载 pending 论文的 PDF；</li>
 *   <li>{@code POST /arxiv/parse} — 批量解析 raw/ 下 PDF 为 JSON；</li>
 *   <li>{@code POST /arxiv/pipeline} — 一键管道（fetch → download → parse → ingest）；</li>
 *   <li>{@code POST /arxiv/process-pending} — 处理全部 pending 论文；</li>
 *   <li>{@code GET /fetch/history[/{id}]} — 抓取历史记录。</li>
 * </ul>
 *
 * <p>{@link FetchService}/{@link ParseService} 均为同步阻塞方法，全部通过
 * {@link Schedulers#boundedElastic()} 异步化；owner 隔离一律取自
 * {@link OwnerFilter#getOwnerId(ServerWebExchange)}。
 */
@RestController
public class ArxivController {

    private static final Logger log = LoggerFactory.getLogger(ArxivController.class);

    /** {@code created_at} 时间格式（与 Python {@code datetime('now', 'localtime')} 对齐）。 */
    private static final DateTimeFormatter CREATED_AT_FORMAT =
            DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

    /** process-pending 一次处理的论文上限（Python {@code limit=200}）。 */
    private static final int PROCESS_PENDING_LIMIT = 200;

    private final FetchService fetchService;
    private final ParseService parseService;
    private final RagService ragService;
    private final PaperRepository paperRepository;
    private final FetchHistoryRepository fetchHistoryRepository;
    private final AppConfig appConfig;
    private final ObjectMapper objectMapper;

    public ArxivController(FetchService fetchService,
                           ParseService parseService,
                           RagService ragService,
                           PaperRepository paperRepository,
                           FetchHistoryRepository fetchHistoryRepository,
                           AppConfig appConfig,
                           ObjectMapper objectMapper) {
        this.fetchService = fetchService;
        this.parseService = parseService;
        this.ragService = ragService;
        this.paperRepository = paperRepository;
        this.fetchHistoryRepository = fetchHistoryRepository;
        this.appConfig = appConfig;
        this.objectMapper = objectMapper;
    }

    // ──────────────────────────────────────────────
    //  Fetch / Download / Parse
    // ──────────────────────────────────────────────

    /** POST /arxiv/fetch — 搜索 arXiv 并保存元数据，返回抓取摘要 + 新论文列表。 */
    @PostMapping("/arxiv/fetch")
    public Mono<Map<String, Object>> fetch(@RequestBody ArxivFetchRequest req,
                                           ServerWebExchange exchange) {
        String ownerId = OwnerFilter.getOwnerId(exchange);
        return Mono.fromCallable(() -> {
            FetchResult result = fetchService.fetchAndPersist(req.getQuery(), req.getMaxResults(), ownerId);

            List<Map<String, Object>> papers = result.papers().stream()
                    .map(p -> {
                        Map<String, Object> item = new LinkedHashMap<>();
                        item.put("arxiv_id", str(p.get("id")));
                        item.put("title", truncate(str(p.get("title")), 120));
                        return item;
                    })
                    .toList();

            saveFetchHistory(
                    req.getQuery(), req.getMaxResults(),
                    result.totalFound(), result.newCount(), result.skippedPapers().size(),
                    result.skippedPapers(), 0, 0, 0, 0, 0, ownerId);

            Map<String, Object> body = new LinkedHashMap<>();
            body.put("status", "ok");
            body.put("count", papers.size());
            body.put("skipped", result.skippedPapers().size());
            body.put("papers", papers);
            return body;
        }).subscribeOn(Schedulers.boundedElastic());
    }

    /** POST /arxiv/download — 下载已抓取（pending）论文的 PDF，返回成功/失败计数。 */
    @PostMapping("/arxiv/download")
    public Mono<Map<String, Object>> download(@RequestBody ArxivFetchRequest req,
                                              ServerWebExchange exchange) {
        String ownerId = OwnerFilter.getOwnerId(exchange);
        return Mono.fromCallable(() -> {
            List<Paper> pending = findPendingPapers(ownerId, req.getMaxResults());
            if (pending.isEmpty()) {
                Map<String, Object> body = new LinkedHashMap<>();
                body.put("status", "ok");
                body.put("downloaded", 0);
                body.put("message", "没有待下载的论文");
                return body;
            }

            List<Map<String, Object>> success = new ArrayList<>();
            List<Map<String, Object>> failed = new ArrayList<>();
            for (Paper p : pending) {
                if (!StringUtils.hasText(p.getPdfUrl())) {
                    continue;
                }
                try {
                    fetchService.downloadPdf(p.getArxivId(), p.getPdfUrl());
                    success.add(Map.of("id", str(p.getArxivId())));
                } catch (Exception e) {
                    log.warn("[ArxivController] 下载失败 {}: {}", p.getArxivId(), e.getMessage());
                    failed.add(Map.of("id", str(p.getArxivId()), "error", safeMessage(e)));
                }
            }

            Map<String, Object> details = new LinkedHashMap<>();
            details.put("success", success);
            details.put("failed", failed);
            Map<String, Object> body = new LinkedHashMap<>();
            body.put("status", "ok");
            body.put("downloaded", success.size());
            body.put("failed", failed.size());
            body.put("details", details);
            return body;
        }).subscribeOn(Schedulers.boundedElastic());
    }

    /** POST /arxiv/parse — 批量解析 raw/ 下全部 PDF 为 parsed/ 下 JSON。 */
    @PostMapping("/arxiv/parse")
    public Mono<Map<String, Object>> parse() {
        return Mono.fromCallable(() -> {
            ParseService.BatchParseResult result = parseService.batchParse(
                    Path.of(appConfig.rawPdfDir()), Path.of(appConfig.parsedDir()));
            Map<String, Object> body = new LinkedHashMap<>();
            body.put("status", "ok");
            body.put("parsed", result.success());
            body.put("failed", result.fail());
            return body;
        }).subscribeOn(Schedulers.boundedElastic());
    }

    // ──────────────────────────────────────────────
    //  Pipeline / process-pending
    // ──────────────────────────────────────────────

    /** POST /arxiv/pipeline — 一键管道：fetch → download → parse → ingest。 */
    @PostMapping("/arxiv/pipeline")
    public Mono<Map<String, Object>> pipeline(@RequestBody ArxivPipelineRequest req,
                                              ServerWebExchange exchange) {
        String ownerId = OwnerFilter.getOwnerId(exchange);
        return Mono.fromCallable(() -> runPipeline(req, ownerId))
                .subscribeOn(Schedulers.boundedElastic());
    }

    /** POST /arxiv/process-pending — 处理全部 pending 论文：下载 → 解析 → 入库。 */
    @PostMapping("/arxiv/process-pending")
    public Mono<Map<String, Object>> processPending(ServerWebExchange exchange) {
        String ownerId = OwnerFilter.getOwnerId(exchange);
        return Mono.fromCallable(() -> runProcessPending(ownerId))
                .subscribeOn(Schedulers.boundedElastic());
    }

    // ──────────────────────────────────────────────
    //  Fetch history
    // ──────────────────────────────────────────────

    /** GET /fetch/history — 分页查询当前用户的抓取历史（Python 契约）。 */
    @GetMapping("/fetch/history")
    public Mono<Map<String, Object>> historyList(@RequestParam(defaultValue = "20") int limit,
                                                 @RequestParam(defaultValue = "0") int offset,
                                                 ServerWebExchange exchange) {
        String ownerId = OwnerFilter.getOwnerId(exchange);
        return Mono.fromCallable(() -> {
            int lim = Math.min(100, Math.max(1, limit));
            int off = Math.max(0, offset);
            List<FetchHistory> all = fetchHistoryRepository.findByOwnerIdOrderByCreatedAtDesc(ownerId);
            List<Map<String, Object>> records = new ArrayList<>();
            int from = Math.min(off, all.size());
            int to = Math.min(off + lim, all.size());
            for (int i = from; i < to; i++) {
                records.add(toFetchHistoryMap(all.get(i)));
            }
            Map<String, Object> body = new LinkedHashMap<>();
            body.put("records", records);
            body.put("total", fetchHistoryRepository.countByOwnerId(ownerId));
            return body;
        }).subscribeOn(Schedulers.boundedElastic());
    }

    /** GET /fetch/history/{id} — 单条抓取记录详情，不存在或非本人时 404。 */
    @GetMapping("/fetch/history/{id}")
    public Mono<Map<String, Object>> historyDetail(@PathVariable Long id,
                                                   ServerWebExchange exchange) {
        String ownerId = OwnerFilter.getOwnerId(exchange);
        return Mono.fromCallable(() -> {
            Optional<FetchHistory> record = fetchHistoryRepository.findById(id)
                    .filter(h -> ownerId.equals(h.getOwnerId()));
            if (record.isEmpty()) {
                throw new ResponseStatusException(HttpStatus.NOT_FOUND, "抓取记录不存在: " + id);
            }
            return toFetchHistoryMap(record.get());
        }).subscribeOn(Schedulers.boundedElastic());
    }

    // ──────────────────────────────────────────────
    //  Pipeline / process-pending 实现
    // ──────────────────────────────────────────────

    private Map<String, Object> runPipeline(ArxivPipelineRequest req, String ownerId) {
        List<Map<String, Object>> steps = new ArrayList<>();

        // 1) fetch — 搜索并保存元数据
        FetchResult fetchResult = fetchService.fetchAndPersist(req.getQuery(), req.getMaxResults(), ownerId);
        List<Map<String, Object>> papers = fetchResult.papers();
        steps.add(stepMap("fetch", papers.size()));

        if (papers.isEmpty()) {
            saveFetchHistory(req.getQuery(), req.getMaxResults(),
                    fetchResult.totalFound(), 0, fetchResult.totalFound(),
                    fetchResult.skippedPapers(), 0, 0, 0, 0, 0, ownerId);
            Map<String, Object> body = new LinkedHashMap<>();
            body.put("status", "ok");
            body.put("steps", steps);
            body.put("message", "arXiv 搜索无结果");
            return body;
        }

        // 2) download — 逐篇下载 PDF
        int dlOk = 0;
        int dlFail = 0;
        List<Map<String, Object>> dlErrors = new ArrayList<>();
        for (Map<String, Object> p : papers) {
            String id = str(p.get("id"));
            String pdfUrl = str(p.get("pdf_url"));
            if (!StringUtils.hasText(pdfUrl)) {
                continue;
            }
            try {
                fetchService.downloadPdf(id, pdfUrl);
                dlOk++;
            } catch (Exception e) {
                dlFail++;
                log.warn("[ArxivController] 管道下载失败 {}: {}", id, e.getMessage());
                dlErrors.add(Map.of("id", id, "error", safeMessage(e)));
            }
        }
        steps.add(stepMap("download", dlOk, dlFail));

        // 3) parse — 对已下载且未解析的论文逐个解析
        int parsedCnt = 0;
        List<Map<String, Object>> parseErrors = new ArrayList<>();
        for (Map<String, Object> p : papers) {
            String id = str(p.get("id"));
            Path pdfPath = Path.of(appConfig.rawPdfDir(), id + ".pdf");
            Path jsonPath = Path.of(appConfig.parsedDir(), id + ".json");
            if (!Files.isRegularFile(pdfPath) || Files.isRegularFile(jsonPath)) {
                continue;
            }
            try {
                ParseService.ParsedDocument doc = parseService.parsePdf(pdfPath);
                Files.createDirectories(jsonPath.getParent());
                objectMapper.writerWithDefaultPrettyPrinter().writeValue(jsonPath.toFile(), doc);
                parsedCnt++;
            } catch (Exception e) {
                log.warn("[ArxivController] 管道解析失败 {}: {}", id, e.getMessage());
                parseErrors.add(Map.of("id", id, "error", truncate(safeMessage(e), 200)));
            }
        }
        steps.add(stepMap("parse", parsedCnt));

        // 4) ingest — 入库（可关闭）
        int ingestPapers = 0;
        int ingestChunks = 0;
        if (req.isAutoIngest()) {
            Map<String, Object> ingestResult = ragService.ingestParsedDir(null, ownerId);
            if (ingestResult.containsKey("error")) {
                steps.add(Map.of("step", "ingest", "error", str(ingestResult.get("error"))));
            } else {
                ingestPapers = intVal(ingestResult.get("papers"));
                ingestChunks = intVal(ingestResult.get("chunks"));
                steps.add(Map.of("step", "ingest", "papers", ingestPapers, "chunks", ingestChunks));
            }
        }

        saveFetchHistory(req.getQuery(), req.getMaxResults(),
                fetchResult.totalFound(), papers.size(),
                Math.max(0, fetchResult.totalFound() - papers.size()),
                fetchResult.skippedPapers(), dlOk, dlFail, parsedCnt, parseErrors.size(),
                ingestPapers, ownerId);

        Map<String, Object> errors = new LinkedHashMap<>();
        errors.put("download", dlErrors);
        errors.put("parse", parseErrors);
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("status", "ok");
        body.put("steps", steps);
        body.put("errors", errors);
        return body;
    }

    private Map<String, Object> runProcessPending(String ownerId) {
        List<Paper> pending = findPendingPapers(ownerId, PROCESS_PENDING_LIMIT);
        List<Paper> withPdf = pending.stream()
                .filter(p -> StringUtils.hasText(p.getPdfUrl()))
                .toList();

        if (withPdf.isEmpty()) {
            Map<String, Object> body = new LinkedHashMap<>();
            body.put("status", "ok");
            body.put("processed", 0);
            body.put("message", "没有待处理的论文");
            return body;
        }

        // 1) download
        int dlOk = 0;
        int dlFail = 0;
        for (Paper p : withPdf) {
            try {
                fetchService.downloadPdf(p.getArxivId(), p.getPdfUrl());
                dlOk++;
            } catch (Exception e) {
                dlFail++;
                log.warn("[ArxivController] process-pending 下载失败 {}: {}", p.getArxivId(), e.getMessage());
            }
        }

        // 2) parse
        int parsedCnt = 0;
        for (Paper p : withPdf) {
            Path pdfPath = Path.of(appConfig.rawPdfDir(), p.getArxivId() + ".pdf");
            Path jsonPath = Path.of(appConfig.parsedDir(), p.getArxivId() + ".json");
            if (!Files.isRegularFile(pdfPath) || Files.isRegularFile(jsonPath)) {
                continue;
            }
            try {
                ParseService.ParsedDocument doc = parseService.parsePdf(pdfPath);
                Files.createDirectories(jsonPath.getParent());
                objectMapper.writerWithDefaultPrettyPrinter().writeValue(jsonPath.toFile(), doc);
                parsedCnt++;
            } catch (Exception e) {
                log.warn("[ArxivController] process-pending 解析失败 {}: {}", p.getArxivId(), e.getMessage());
            }
        }

        // 3) ingest
        int ingested = 0;
        int chunks = 0;
        String ingestError = "";
        if (!withPdf.isEmpty()) {
            Map<String, Object> ingestResult = ragService.ingestParsedDir(null, ownerId);
            if (ingestResult.containsKey("error")) {
                ingestError = str(ingestResult.get("error"));
                log.error("[ArxivController] process-pending 入库失败: {}", ingestError);
            } else {
                ingested = intVal(ingestResult.get("papers"));
                chunks = intVal(ingestResult.get("chunks"));
            }
        }

        saveFetchHistory("<手动处理待入库>", withPdf.size(),
                withPdf.size(), withPdf.size(), 0, List.of(),
                dlOk, dlFail, parsedCnt, Math.max(0, dlOk - parsedCnt), ingested, ownerId);

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("status", "ok");
        body.put("total", withPdf.size());
        body.put("downloaded", dlOk);
        body.put("download_failed", dlFail);
        body.put("parsed", parsedCnt);
        body.put("ingested", ingested);
        body.put("chunks", chunks);
        body.put("ingest_error", ingestError);
        return body;
    }

    // ──────────────────────────────────────────────
    //  Fetch history 持久化（Python _save_fetch_history 移植）
    // ──────────────────────────────────────────────

    /** 写抓取历史，失败不影响主流程。 */
    private void saveFetchHistory(String query, int maxResults,
                                  int totalFound, int fetched, int skipped,
                                  List<Map<String, Object>> skippedPapers,
                                  int downloadSuccess, int downloadFailed,
                                  int parseSuccess, int parseFailed,
                                  int ingested, String ownerId) {
        try {
            String skippedJson = objectMapper.writeValueAsString(
                    skippedPapers == null ? List.of() : skippedPapers);
            FetchHistory record = FetchHistory.builder()
                    .queryText(query != null ? query : "")
                    .maxResults(maxResults)
                    .totalFound(totalFound)
                    .fetched(fetched)
                    .skipped(skipped)
                    .downloadSuccess(downloadSuccess)
                    .downloadFailed(downloadFailed)
                    .parseSuccess(parseSuccess)
                    .parseFailed(parseFailed)
                    .ingested(ingested)
                    .skippedPapers(skippedJson)
                    .ownerId(ownerId)
                    .build();
            fetchHistoryRepository.save(record);
            log.info("[ArxivController] 抓取历史已保存: id={} query={} fetched={} skipped={}",
                    record.getId(), truncate(query, 50), fetched, skipped);
        } catch (Exception e) {
            log.warn("[ArxivController] 保存抓取历史失败: {}", e.getMessage());
        }
    }

    /** 把实体转换为 Python {@code FetchHistory.to_dict()} 契约（skipped_papers 为数组）。 */
    private Map<String, Object> toFetchHistoryMap(FetchHistory h) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("id", h.getId());
        map.put("query_text", nvl(h.getQueryText()));
        map.put("max_results", nvl(h.getMaxResults()));
        map.put("total_found", nvl(h.getTotalFound()));
        map.put("fetched", nvl(h.getFetched()));
        map.put("skipped", nvl(h.getSkipped()));
        map.put("download_success", nvl(h.getDownloadSuccess()));
        map.put("download_failed", nvl(h.getDownloadFailed()));
        map.put("parse_success", nvl(h.getParseSuccess()));
        map.put("parse_failed", nvl(h.getParseFailed()));
        map.put("ingested", nvl(h.getIngested()));
        map.put("skipped_papers", parseSkippedPapers(h.getSkippedPapers()));
        map.put("owner_id", nvl(h.getOwnerId()));
        map.put("created_at", h.getCreatedAt() != null ? h.getCreatedAt().format(CREATED_AT_FORMAT) : "");
        return map;
    }

    /** 把库中存储的 skipped_papers JSON 字符串还原为数组（前端期望 {@code SkippedPaper[]}）。 */
    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> parseSkippedPapers(String json) {
        if (json == null || json.isBlank()) {
            return List.of();
        }
        try {
            return (List<Map<String, Object>>) objectMapper.readValue(json, List.class);
        } catch (Exception e) {
            log.warn("[ArxivController] 解析 skipped_papers 失败: {}", e.getMessage());
            return List.of();
        }
    }

    // ──────────────────────────────────────────────
    //  Private helpers
    // ──────────────────────────────────────────────

    /** 查询某用户 status=pending 的论文（Python {@code find_all(..., owner_id)}）。 */
    private List<Paper> findPendingPapers(String ownerId, int limit) {
        return paperRepository.search(null, null, null, null, null, null,
                "pending", ownerId, Math.max(1, limit));
    }

    private static Map<String, Object> stepMap(String step, int count) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("step", step);
        m.put("count", count);
        return m;
    }

    private static Map<String, Object> stepMap(String step, int success, int failed) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("step", step);
        m.put("success", success);
        m.put("failed", failed);
        return m;
    }

    private static String str(Object v) {
        return v == null ? "" : String.valueOf(v);
    }

    private static int intVal(Object v) {
        if (v instanceof Number n) {
            return n.intValue();
        }
        return 0;
    }

    private static int nvl(Integer v) {
        return v == null ? 0 : v;
    }

    private static String nvl(String s) {
        return s == null ? "" : s;
    }

    private static String truncate(String s, int maxLen) {
        if (s == null) {
            return "";
        }
        return s.length() <= maxLen ? s : s.substring(0, maxLen);
    }

    private static String safeMessage(Exception e) {
        return e.getMessage() != null ? e.getMessage() : e.getClass().getSimpleName();
    }
}
