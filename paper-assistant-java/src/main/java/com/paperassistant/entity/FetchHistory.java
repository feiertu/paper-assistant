package com.paperassistant.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

/**
 * 抓取历史（对应 {@code fetch_history} 表），记录每次 arXiv 抓取任务的统计信息。
 */
@Entity
@Table(name = "fetch_history")
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class FetchHistory {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "query_text", nullable = false)
    private String queryText;

    @Column(name = "max_results", nullable = false)
    private Integer maxResults;

    @Column(name = "total_found")
    private Integer totalFound;

    @Column(name = "fetched")
    private Integer fetched;

    @Column(name = "skipped")
    private Integer skipped;

    @Column(name = "download_success")
    private Integer downloadSuccess;

    @Column(name = "download_failed")
    private Integer downloadFailed;

    @Column(name = "parse_success")
    private Integer parseSuccess;

    @Column(name = "parse_failed")
    private Integer parseFailed;

    @Column(name = "ingested")
    private Integer ingested;

    @Column(name = "skipped_papers")
    private String skippedPapers;

    @Column(name = "owner_id")
    private String ownerId;

    @Column(name = "created_at", insertable = false, updatable = false)
    private LocalDateTime createdAt;
}
