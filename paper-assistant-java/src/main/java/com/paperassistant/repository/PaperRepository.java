package com.paperassistant.repository;

import com.paperassistant.entity.Paper;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;
import java.util.Optional;

/**
 * 论文仓库（{@code papers} 表）。
 *
 * <p>JPQL 一律使用实体字段名而非列名。特别注意：{@code abstract} 是 Java 关键字，
 * 实体字段为 {@link Paper#getAbstractText() abstractText}（列名 {@code abstract}），
 * 因此任何 JPQL 中引用摘要字段必须写 {@code p.abstractText}。
 * 原生 SQL（{@code nativeQuery = true}）中则照常使用列名（{@code p.abstract}）。
 */
public interface PaperRepository extends JpaRepository<Paper, Long> {

    /**
     * 按 arxivId + ownerId 精确查找单篇论文。
     */
    Optional<Paper> findByArxivIdAndOwnerId(String arxivId, String ownerId);

    /**
     * 全局按 arxivId 精确查找单篇论文（papers.arxiv_id 为全局 UNIQUE）。
     * 用于引用图查询判断被引/引用论文是否已入库（Python {@code LEFT JOIN papers}）。
     */
    Optional<Paper> findByArxivId(String arxivId);

    /**
     * 分页查询某用户全部论文，按创建时间倒序。
     */
    @Query("SELECT p FROM Paper p WHERE p.ownerId = :ownerId ORDER BY p.createdAt DESC")
    List<Paper> findAllByOwnerId(@Param("ownerId") String ownerId, Pageable pageable);

    /**
     * 统计某用户的论文总数。
     */
    long countByOwnerId(String ownerId);

    /**
     * 查询某用户已成功解析（ingested）的论文，按创建时间倒序。
     */
    @Query("SELECT p FROM Paper p WHERE p.ingestStatus = 'ingested' AND p.ownerId = :ownerId ORDER BY p.createdAt DESC")
    List<Paper> findIngestedByOwnerId(@Param("ownerId") String ownerId);

    /**
     * 查询某用户已存在的论文 arxiv_id 列表（用于抓取时去重跳过）。
     */
    @Query(value = "SELECT arxiv_id FROM papers WHERE ingest_status = 'ingested' AND owner_id = :ownerId", nativeQuery = true)
    List<String> findExistingIds(@Param("ownerId") String ownerId);

    /**
     * 查询某用户全部论文的 arxiv_id 列表。
     */
    @Query(value = "SELECT arxiv_id FROM papers WHERE owner_id = :ownerId", nativeQuery = true)
    List<String> findAllIds(@Param("ownerId") String ownerId);

    /**
     * 综合检索（原生 SQL，走 PostgreSQL tsvector 全文检索 + 可选过滤条件）。
     *
     * <p>各过滤参数均可为 {@code null}（表示不过滤）；{@code keyword} 走
     * {@code tsv @@ plainto_tsquery('english', :keyword)}（使用 V1 迁移生成的
     * {@code papers.tsv} 生成列）。排序按创建时间倒序，结果数受 {@code limit} 限制。
     */
    @Query(value = """
        SELECT p.* FROM papers p WHERE p.owner_id = :ownerId
        AND (:keyword IS NULL OR p.tsv @@ plainto_tsquery('english', :keyword))
        AND (:arxivId IS NULL OR p.arxiv_id ILIKE '%' || :arxivId || '%')
        AND (:author IS NULL OR p.authors ILIKE '%' || :author || '%')
        AND (:yearFrom IS NULL OR p.published >= :yearFrom)
        AND (:yearTo IS NULL OR p.published <= :yearTo || '-12-31')
        AND (:source IS NULL OR p.source = :source)
        AND (:status IS NULL OR p.ingest_status = :status)
        ORDER BY p.created_at DESC LIMIT :limit
        """, nativeQuery = true)
    List<Paper> search(@Param("keyword") String keyword,
        @Param("arxivId") String arxivId, @Param("author") String author,
        @Param("yearFrom") String yearFrom, @Param("yearTo") String yearTo,
        @Param("source") String source, @Param("status") String status,
        @Param("ownerId") String ownerId, @Param("limit") int limit);

    /**
     * pgvector 余弦距离相似度查询（原生 SQL，使用 PostgreSQL {@code <=>} 操作符）。
     *
     * <p><b>{@code queryEmbedding} 参数必须格式化为 pgvector 字面量字符串</b>，
     * 形如 {@code "[0.1,0.2,0.3,...]"}（中括号括起、逗号分隔的浮点数），
     * 维度须为 1024（与 {@code embedding vector(1024)} 列一致）。这是
     * {@code CAST(:queryEmbedding AS vector)} 的数据库端要求——传入裸逗号字符串
     * 或 {@code float[]} 的 {@code toString()} 都会导致 cast 失败。
     *
     * <p>返回 {@link List}<{@link Paper}>：结果集额外的 {@code distance} 计算列
     * 仅用于排序，Hibernate 在映射实体时会忽略它。
     */
    @Query(value = """
        SELECT *, embedding <=> CAST(:queryEmbedding AS vector) AS distance
        FROM papers WHERE owner_id = :ownerId
        ORDER BY embedding <=> CAST(:queryEmbedding AS vector)
        LIMIT :limit
        """, nativeQuery = true)
    List<Paper> findSimilarByEmbedding(@Param("queryEmbedding") String queryEmbedding,
        @Param("ownerId") String ownerId, @Param("limit") int limit);
}
