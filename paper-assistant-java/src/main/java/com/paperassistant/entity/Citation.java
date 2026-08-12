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
 * 论文引用关系（对应 {@code citations} 表），记录论文间引用链接。
 */
@Entity
@Table(name = "citations")
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class Citation {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "citing_arxiv_id", nullable = false)
    private String citingArxivId;

    @Column(name = "cited_arxiv_id", nullable = false)
    private String citedArxivId;

    @Column(name = "cited_title")
    private String citedTitle;

    @Column(name = "context")
    private String context;

    @Column(name = "created_at", insertable = false, updatable = false)
    private LocalDateTime createdAt;
}
