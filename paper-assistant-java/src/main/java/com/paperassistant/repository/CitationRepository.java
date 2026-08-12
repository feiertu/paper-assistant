package com.paperassistant.repository;

import com.paperassistant.entity.Citation;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;

import java.util.List;
import java.util.Map;

/**
 * 论文引用关系仓库（{@code citations} 表）。
 */
public interface CitationRepository extends JpaRepository<Citation, Long> {

    /**
     * 查询引用某篇论文的所有记录（按 citing_arxiv_id 关联）。
     */
    List<Citation> findByCitingArxivId(String citingArxivId);

    /**
     * 查询被某篇论文引用的所有记录（按 cited_arxiv_id 关联）。
     */
    List<Citation> findByCitedArxivId(String citedArxivId);

    /**
     * 判断某对引用关系是否存在（citations 表有唯一约束，用于去重）。
     */
    long countByCitingArxivIdAndCitedArxivId(String citingArxivId, String citedArxivId);

    /**
     * 统计不重复的 citing（出向引用）论文数。
     */
    @Query(value = "SELECT COUNT(DISTINCT citing_arxiv_id) FROM citations", nativeQuery = true)
    long countDistinctCiting();

    /**
     * 统计不重复的 cited（入向引用）论文数。
     */
    @Query(value = "SELECT COUNT(DISTINCT cited_arxiv_id) FROM citations", nativeQuery = true)
    long countDistinctCited();

    /**
     * 被引次数最多的论文（top-N）。
     */
    @Query(value = """
        SELECT cited_arxiv_id AS arxiv_id, COUNT(*) AS cnt
        FROM citations GROUP BY cited_arxiv_id
        ORDER BY cnt DESC LIMIT :limit
        """, nativeQuery = true)
    List<Map<String, Object>> topCitedBy(int limit);

    /**
     * 引用他文最多的论文（top-N）。
     */
    @Query(value = """
        SELECT citing_arxiv_id AS arxiv_id, COUNT(*) AS cnt
        FROM citations GROUP BY citing_arxiv_id
        ORDER BY cnt DESC LIMIT :limit
        """, nativeQuery = true)
    List<Map<String, Object>> topCiters(int limit);
}
