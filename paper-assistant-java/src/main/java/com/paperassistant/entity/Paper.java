package com.paperassistant.entity;

import com.fasterxml.jackson.annotation.JsonProperty;
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
 * 论文元数据（对应 {@code papers} 表）。
 *
 * <p>注意：{@code abstract} 是 Java 关键字，因此字段命名为 {@code abstractText}，
 * 列名映射为 {@code abstract}，并通过 {@link JsonProperty} 覆盖全局 snake_case 命名策略，
 * 使响应 JSON 仍为 {@code abstract}（与 Python/FastAPI 及前端契约一致）。
 *
 * <p>{@code embedding} 为 pgvector 向量列，{@code float[]} 对应维度 1024；
 * 运行时读写需要注册 pgvector 的 Hibernate 类型（后续任务处理），本实体仅负责映射声明。
 */
@Entity
@Table(name = "papers")
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class Paper {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "arxiv_id", nullable = false, unique = true)
    private String arxivId;

    @Column(name = "title")
    private String title;

    @Column(name = "authors")
    private String authors;

    @Column(name = "abstract")
    @JsonProperty("abstract")
    private String abstractText;

    @Column(name = "published")
    private String published;

    @Column(name = "pdf_url")
    private String pdfUrl;

    @Column(name = "source")
    private String source;

    @Column(name = "ingest_status")
    @Builder.Default
    private String ingestStatus = "pending";

    @Column(name = "chunk_count")
    @Builder.Default
    private Integer chunkCount = 0;

    @Column(name = "owner_id")
    private String ownerId;

    @Column(name = "created_at", insertable = false, updatable = false)
    private LocalDateTime createdAt;

    @Column(name = "embedding", columnDefinition = "vector(1024)")
    private float[] embedding;
}
