package com.paperassistant.repository;

import com.paperassistant.entity.Citation;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

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
}
