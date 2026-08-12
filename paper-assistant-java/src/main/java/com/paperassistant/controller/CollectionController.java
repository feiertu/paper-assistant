package com.paperassistant.controller;

import com.paperassistant.dto.request.CollectionPaperRequest;
import com.paperassistant.dto.request.CreateCollectionRequest;
import com.paperassistant.entity.Paper;
import com.paperassistant.entity.PaperCollection;
import com.paperassistant.filter.OwnerFilter;
import com.paperassistant.repository.CollectionRepository;
import com.paperassistant.repository.PaperRepository;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.DeleteMapping;
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

import java.time.format.DateTimeFormatter;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 收藏夹端点 — Python {@code src/api/main.py} 的 {@code /collections*} 路由族。
 *
 * <p>收藏夹 CRUD：列表、创建、删除，以及向收藏夹添加/查询论文。
 * {@code collections} 表没有 {@code owner_id} 列（与 Python DAO 一致，收藏夹不区分所有者），
 * 因此收藏夹列表/创建/删除不做 owner 过滤；收藏夹内论文列表则沿用
 * {@link CollectionRepository#findPapersByCollectionId} 的 owner 隔离。
 *
 * <p>连接表 {@code collection_papers} 为纯 SQL 表（无 JPA 实体），添加论文与维护
 * {@code paper_count} 通过 {@link JdbcTemplate} 完成。所有阻塞调用走
 * {@link Schedulers#boundedElastic()}。
 */
@RestController
public class CollectionController {

    /** {@code created_at} 时间格式（与 Python {@code datetime('now', 'localtime')} 对齐）。 */
    private static final DateTimeFormatter CREATED_AT_FORMAT =
            DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

    private final CollectionRepository collectionRepository;
    private final PaperRepository paperRepository;
    private final JdbcTemplate jdbcTemplate;

    public CollectionController(CollectionRepository collectionRepository,
                                PaperRepository paperRepository,
                                JdbcTemplate jdbcTemplate) {
        this.collectionRepository = collectionRepository;
        this.paperRepository = paperRepository;
        this.jdbcTemplate = jdbcTemplate;
    }

    /** GET /collections — 收藏夹列表（分页）。 */
    @GetMapping("/collections")
    public Mono<Map<String, Object>> list(@RequestParam(defaultValue = "50") int limit,
                                          @RequestParam(defaultValue = "0") int offset) {
        return Mono.fromCallable(() -> {
            int lim = Math.max(1, limit);
            Pageable pageable = PageRequest.of(Math.max(0, offset) / lim, lim);
            Page<PaperCollection> page = collectionRepository.findAll(pageable);
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("collections",
                    page.getContent().stream().map(this::toCollectionMap).toList());
            result.put("total", page.getTotalElements());
            return result;
        }).subscribeOn(Schedulers.boundedElastic());
    }

    /** POST /collections — 创建收藏夹，返回 {@code {"id": ..., "status": "ok"}}。 */
    @PostMapping("/collections")
    public Mono<Map<String, Object>> create(@RequestBody CreateCollectionRequest req) {
        return Mono.fromCallable(() -> {
            PaperCollection collection = PaperCollection.builder()
                    .name(req.getName())
                    .description(req.getDescription())
                    .paperCount(0)
                    .build();
            PaperCollection saved = collectionRepository.save(collection);
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("id", saved.getId());
            result.put("status", "ok");
            return result;
        }).subscribeOn(Schedulers.boundedElastic());
    }

    /** DELETE /collections/{id} — 删除收藏夹（级联清理连接表），不存在时 404。 */
    @DeleteMapping("/collections/{id}")
    public Mono<Map<String, Object>> delete(@PathVariable Long id) {
        return Mono.fromCallable(() -> {
            if (!collectionRepository.existsById(id)) {
                throw new ResponseStatusException(HttpStatus.NOT_FOUND, "收藏夹不存在: " + id);
            }
            collectionRepository.deleteById(id);
            return Map.<String, Object>of("status", "ok");
        }).subscribeOn(Schedulers.boundedElastic());
    }

    /** POST /collections/{id}/papers — 向收藏夹添加论文（幂等），并刷新 paper_count。 */
    @PostMapping("/collections/{id}/papers")
    public Mono<Map<String, Object>> addPaper(@PathVariable Long id,
                                              @RequestBody CollectionPaperRequest req) {
        return Mono.fromCallable(() -> {
            if (!collectionRepository.existsById(id)) {
                throw new ResponseStatusException(HttpStatus.NOT_FOUND, "收藏夹不存在: " + id);
            }
            long paperId = req.getPaperId();
            if (!paperRepository.existsById(paperId)) {
                throw new ResponseStatusException(HttpStatus.NOT_FOUND, "论文不存在: " + paperId);
            }
            // 幂等插入（连接表联合主键为 (collection_id, paper_id)）
            jdbcTemplate.update(
                    "INSERT INTO collection_papers (collection_id, paper_id) "
                            + "VALUES (?, ?) ON CONFLICT DO NOTHING",
                    id, paperId);
            refreshPaperCount(id);
            return Map.<String, Object>of("status", "ok");
        }).subscribeOn(Schedulers.boundedElastic());
    }

    /** GET /collections/{id}/papers — 收藏夹内论文列表（owner 过滤 + 分页）。 */
    @GetMapping("/collections/{id}/papers")
    public Mono<Map<String, Object>> listPapers(@PathVariable Long id,
                                                @RequestParam(defaultValue = "50") int limit,
                                                @RequestParam(defaultValue = "0") int offset,
                                                ServerWebExchange exchange) {
        String ownerId = OwnerFilter.getOwnerId(exchange);
        return Mono.fromCallable(() -> {
            if (!collectionRepository.existsById(id)) {
                throw new ResponseStatusException(HttpStatus.NOT_FOUND, "收藏夹不存在: " + id);
            }
            List<Paper> papers = collectionRepository.findPapersByCollectionId(id, ownerId);
            int lim = Math.max(1, limit);
            int off = Math.max(0, offset);
            int from = Math.min(off, papers.size());
            int to = Math.min(off + lim, papers.size());
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("papers", papers.subList(from, to).stream().map(this::toPaperMap).toList());
            result.put("total", papers.size());
            return result;
        }).subscribeOn(Schedulers.boundedElastic());
    }

    // ──────────────────────────────────────────────
    //  Private helpers
    // ──────────────────────────────────────────────

    /** 用连接表实时统计值刷新 {@code collections.paper_count}（与 Python {@code add_paper} 一致）。 */
    private void refreshPaperCount(Long collectionId) {
        long count = collectionRepository.countPapersByCollectionId(collectionId);
        jdbcTemplate.update("UPDATE collections SET paper_count = ? WHERE id = ?", count, collectionId);
    }

    /** 收藏夹响应字段 — 与 Python {@code Collection.to_dict()} 对齐。 */
    private Map<String, Object> toCollectionMap(PaperCollection c) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("id", c.getId());
        map.put("name", c.getName());
        map.put("description", c.getDescription() != null ? c.getDescription() : "");
        map.put("paper_count", c.getPaperCount() != null ? c.getPaperCount() : 0);
        map.put("created_at", c.getCreatedAt() != null ? c.getCreatedAt().format(CREATED_AT_FORMAT) : "");
        return map;
    }

    /** 论文响应字段 — 与 Python {@code Paper.to_dict()} 对齐（不含 embedding 向量）。 */
    private Map<String, Object> toPaperMap(Paper p) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("id", p.getId());
        map.put("arxiv_id", p.getArxivId());
        map.put("title", p.getTitle() != null ? p.getTitle() : "");
        map.put("authors", p.getAuthors() != null ? p.getAuthors() : "");
        map.put("abstract", p.getAbstractText() != null ? p.getAbstractText() : "");
        map.put("published", p.getPublished() != null ? p.getPublished() : "");
        map.put("pdf_url", p.getPdfUrl() != null ? p.getPdfUrl() : "");
        map.put("source", p.getSource() != null ? p.getSource() : "");
        map.put("ingest_status", p.getIngestStatus() != null ? p.getIngestStatus() : "pending");
        map.put("chunk_count", p.getChunkCount() != null ? p.getChunkCount() : 0);
        map.put("owner_id", p.getOwnerId() != null ? p.getOwnerId() : "");
        map.put("created_at", p.getCreatedAt() != null ? p.getCreatedAt().format(CREATED_AT_FORMAT) : "");
        return map;
    }
}
