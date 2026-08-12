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
 * 查询历史（对应 {@code queries} 表）。
 *
 * <p>类名取 {@code QueryRecord} 以避免与 JPA 的 {@code javax.persistence.Query} 冲突。
 */
@Entity
@Table(name = "queries")
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class QueryRecord {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "query_text", nullable = false)
    private String queryText;

    @Column(name = "answer_text")
    private String answerText;

    @Column(name = "lang")
    @Builder.Default
    private String lang = "zh";

    @Column(name = "hit_count")
    @Builder.Default
    private Integer hitCount = 0;

    @Column(name = "owner_id")
    private String ownerId;

    @Column(name = "created_at", insertable = false, updatable = false)
    private LocalDateTime createdAt;
}
