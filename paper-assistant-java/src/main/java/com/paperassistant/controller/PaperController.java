package com.paperassistant.controller;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.paperassistant.config.AppConfig;
import com.paperassistant.dto.request.AnalyzeRequest;
import com.paperassistant.dto.request.RecommendRequest;
import com.paperassistant.entity.Paper;
import com.paperassistant.filter.OwnerFilter;
import com.paperassistant.repository.PaperRepository;
import com.paperassistant.service.RagService;
import org.springframework.core.io.FileSystemResource;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
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
import java.util.regex.Pattern;

/**
 * 论文元数据 / 文件 / RAG 端点 — Python {@code src/api/main.py} 的
 * {@code /papers*} 路由族。
 *
 * <p>包括：分页列表、单篇详情、多条件全文检索、PDF 在线预览（含路径遍历防护）、
 * 解析内容（sections/subsections）、基于向量相似度的推荐与全局论文分析。
 *
 * <p>所有阻塞调用（JPA / 文件 I/O / RAG）均通过
 * {@link Schedulers#boundedElastic()} 异步化；owner 隔离一律取自
 * {@link OwnerFilter#getOwnerId(ServerWebExchange)}。响应 JSON 的字段名沿用
 * Python {@code Paper.to_dict()}（全局 snake_case 策略）。
 */
@RestController
public class PaperController {

    /** arXiv id 合法格式（与 Python {@code re.match(r'^[\w.-]+$', arxiv_id)} 一致）。 */
    private static final Pattern ARXIV_ID_RE = Pattern.compile("[\\w.\\-]+");

    /** {@code created_at} 时间格式（与 Python {@code datetime('now', 'localtime')} 对齐）。 */
    private static final DateTimeFormatter CREATED_AT_FORMAT =
            DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

    private final PaperRepository paperRepository;
    private final RagService ragService;
    private final AppConfig appConfig;
    private final ObjectMapper objectMapper;

    public PaperController(PaperRepository paperRepository,
                           RagService ragService,
                           AppConfig appConfig,
                           ObjectMapper objectMapper) {
        this.paperRepository = paperRepository;
        this.ragService = ragService;
        this.appConfig = appConfig;
        this.objectMapper = objectMapper;
    }

    /** GET /papers — 当前用户的分页论文列表。 */
    @GetMapping("/papers")
    public Mono<Map<String, Object>> list(@RequestParam(defaultValue = "50") int limit,
                                          @RequestParam(defaultValue = "0") int offset,
                                          ServerWebExchange exchange) {
        String ownerId = OwnerFilter.getOwnerId(exchange);
        return Mono.fromCallable(() -> {
            int lim = Math.max(1, limit);
            Pageable pageable = PageRequest.of(Math.max(0, offset) / lim, lim);
            List<Paper> papers = paperRepository.findAllByOwnerId(ownerId, pageable);
            long total = paperRepository.countByOwnerId(ownerId);
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("papers", papers.stream().map(this::toPaperMap).toList());
            result.put("total", total);
            return result;
        }).subscribeOn(Schedulers.boundedElastic());
    }

    /** GET /papers/{arxivId} — 单篇论文详情，不存在时 404。 */
    @GetMapping("/papers/{arxivId}")
    public Mono<Map<String, Object>> get(@PathVariable String arxivId, ServerWebExchange exchange) {
        String ownerId = OwnerFilter.getOwnerId(exchange);
        return Mono.fromCallable(() ->
                paperRepository.findByArxivIdAndOwnerId(arxivId, ownerId)
                        .map(this::toPaperMap)
                        .orElseThrow(() -> new ResponseStatusException(
                                HttpStatus.NOT_FOUND, "论文不存在: " + arxivId)))
                .subscribeOn(Schedulers.boundedElastic());
    }

    /** GET /papers/search — 多条件全文检索（tsvector + 过滤），按 owner 隔离。 */
    @GetMapping("/papers/search")
    public Mono<Map<String, Object>> search(
            @RequestParam(defaultValue = "") String keyword,
            @RequestParam(name = "arxiv_id", defaultValue = "") String arxivId,
            @RequestParam(defaultValue = "") String author,
            @RequestParam(name = "year_from", defaultValue = "") String yearFrom,
            @RequestParam(name = "year_to", defaultValue = "") String yearTo,
            @RequestParam(defaultValue = "") String source,
            @RequestParam(defaultValue = "") String status,
            @RequestParam(name = "sort_by", defaultValue = "created_at") String sortBy,
            @RequestParam(defaultValue = "50") int limit,
            ServerWebExchange exchange) {
        String ownerId = OwnerFilter.getOwnerId(exchange);
        int lim = Math.min(500, Math.max(1, limit));
        return Mono.fromCallable(() -> {
            List<Paper> papers = paperRepository.search(
                    nullIfBlank(keyword), nullIfBlank(arxivId), nullIfBlank(author),
                    nullIfBlank(yearFrom), nullIfBlank(yearTo), nullIfBlank(source),
                    nullIfBlank(status), ownerId, lim);
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("papers", papers.stream().map(this::toPaperMap).toList());
            result.put("total", papers.size());
            return result;
        }).subscribeOn(Schedulers.boundedElastic());
    }

    /** GET /papers/{arxivId}/pdf — 在线预览 PDF（含路径遍历防护）。 */
    @GetMapping("/papers/{arxivId}/pdf")
    public Mono<ResponseEntity<FileSystemResource>> pdf(@PathVariable String arxivId) {
        return Mono.fromCallable(() -> {
            Path pdf = resolvePdfPath(arxivId);
            FileSystemResource resource = new FileSystemResource(pdf);
            return ResponseEntity.ok()
                    .contentType(MediaType.APPLICATION_PDF)
                    .header(HttpHeaders.CONTENT_DISPOSITION,
                            "inline; filename=\"" + arxivId + ".pdf\"")
                    .body(resource);
        }).subscribeOn(Schedulers.boundedElastic());
    }

    /** GET /papers/{arxivId}/content — 返回解析 JSON 的 sections/subsections。 */
    @GetMapping("/papers/{arxivId}/content")
    public Mono<Map<String, Object>> content(@PathVariable String arxivId) {
        return Mono.fromCallable(() -> readSections(arxivId))
                .subscribeOn(Schedulers.boundedElastic());
    }

    /** POST /papers/recommend — 基于向量相似度推荐相关论文。 */
    @PostMapping("/papers/recommend")
    public Mono<Map<String, Object>> recommend(@RequestBody RecommendRequest req) {
        return Mono.fromCallable(() -> {
            List<Map<String, Object>> similar =
                    ragService.recommendSimilar(req.getArxivId(), req.getTopK());
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("arxiv_id", req.getArxivId());
            result.put("similar", similar);
            return result;
        }).subscribeOn(Schedulers.boundedElastic());
    }

    /** POST /papers/analyze — 对当前用户全部论文做全局分析。 */
    @PostMapping("/papers/analyze")
    public Mono<Map<String, Object>> analyze(@RequestBody AnalyzeRequest req,
                                             ServerWebExchange exchange) {
        String ownerId = OwnerFilter.getOwnerId(exchange);
        return Mono.fromCallable(() -> {
            String analysis = ragService.analyzeAllPapers(req.getQuery(), req.getLang(), ownerId);
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("analysis", analysis);
            return result;
        }).subscribeOn(Schedulers.boundedElastic());
    }

    // ──────────────────────────────────────────────
    //  Private helpers
    // ──────────────────────────────────────────────

    /**
     * 解析并校验 PDF 路径：
     * <ol>
     *   <li>校验 arxiv_id 合法（拒绝 {@code ..}、{@code /}、{@code \}，且仅含 {@code \w.-}）；</li>
     *   <li>{@code rawPdfDir.resolve(arxivId + ".pdf")} 规范化后必须仍在 rawPdfDir 之下；</li>
     *   <li>文件必须存在。</li>
     * </ol>
     */
    private Path resolvePdfPath(String arxivId) {
        validateArxivId(arxivId);
        Path rawDir = Path.of(appConfig.rawPdfDir()).toAbsolutePath().normalize();
        Path pdf = rawDir.resolve(arxivId + ".pdf").normalize();
        if (!pdf.startsWith(rawDir)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "非法的 PDF 路径: " + arxivId);
        }
        if (!Files.isRegularFile(pdf)) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "PDF 不存在: " + arxivId);
        }
        return pdf;
    }

    /** 从 {@code config.parsedDir()/arxivId.json} 读取 sections（Python {@code /content} 格式）。 */
    private Map<String, Object> readSections(String arxivId) {
        validateArxivId(arxivId);
        Path parsedDir = Path.of(appConfig.parsedDir()).toAbsolutePath().normalize();
        Path jsonPath = parsedDir.resolve(arxivId + ".json").normalize();
        if (!jsonPath.startsWith(parsedDir)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "非法的 arxiv_id: " + arxivId);
        }
        if (!Files.isRegularFile(jsonPath)) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "未找到解析文件: " + arxivId);
        }
        try {
            JsonNode root = objectMapper.readTree(jsonPath.toFile());
            List<Map<String, Object>> sections = new ArrayList<>();
            JsonNode sectionsNode = root.get("sections");
            if (sectionsNode != null && sectionsNode.isArray()) {
                for (JsonNode sec : sectionsNode) {
                    Map<String, Object> item = new LinkedHashMap<>();
                    item.put("title", textOr(sec, "title", "Untitled"));
                    item.put("content", textOr(sec, "content", ""));
                    List<Map<String, Object>> subs = new ArrayList<>();
                    JsonNode subsNode = sec.get("subsections");
                    if (subsNode != null && subsNode.isArray()) {
                        for (JsonNode sub : subsNode) {
                            Map<String, Object> subItem = new LinkedHashMap<>();
                            subItem.put("title", textOr(sub, "title", ""));
                            subItem.put("content", textOr(sub, "content", ""));
                            subs.add(subItem);
                        }
                    }
                    item.put("subsections", subs);
                    sections.add(item);
                }
            }
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("sections", sections);
            result.put("total", sections.size());
            return result;
        } catch (IOException e) {
            throw new ResponseStatusException(HttpStatus.INTERNAL_SERVER_ERROR,
                    "读取解析文件失败: " + arxivId);
        }
    }

    /** 拒绝包含路径分隔符/点目录的 arxiv_id，并对非法字符做白名单校验。 */
    private static void validateArxivId(String arxivId) {
        if (arxivId == null || arxivId.isBlank()
                || arxivId.contains("..")
                || arxivId.contains("/")
                || arxivId.contains("\\")
                || !ARXIV_ID_RE.matcher(arxivId).matches()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "无效的 arxiv_id: " + arxivId);
        }
    }

    /** 论文响应字段 — 与 Python {@code Paper.to_dict()} 对齐（不含 embedding 向量）。 */
    private Map<String, Object> toPaperMap(Paper p) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("id", p.getId());
        map.put("arxiv_id", p.getArxivId());
        map.put("title", nvl(p.getTitle()));
        map.put("authors", nvl(p.getAuthors()));
        map.put("abstract", nvl(p.getAbstractText()));
        map.put("published", nvl(p.getPublished()));
        map.put("pdf_url", nvl(p.getPdfUrl()));
        map.put("source", nvl(p.getSource()));
        map.put("ingest_status", p.getIngestStatus() != null ? p.getIngestStatus() : "pending");
        map.put("chunk_count", p.getChunkCount() != null ? p.getChunkCount() : 0);
        map.put("owner_id", nvl(p.getOwnerId()));
        map.put("created_at", p.getCreatedAt() != null ? p.getCreatedAt().format(CREATED_AT_FORMAT) : "");
        return map;
    }

    private static String textOr(JsonNode node, String field, String fallback) {
        JsonNode value = node.get(field);
        return value == null || value.isNull() ? fallback : value.asText();
    }

    private static String nullIfBlank(String s) {
        return s == null || s.isBlank() ? null : s;
    }

    private static String nvl(String s) {
        return s == null ? "" : s;
    }
}
