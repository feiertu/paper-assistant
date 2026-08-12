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
 * 论文收藏夹（对应 {@code collections} 表）。
 *
 * <p>类名取 {@code PaperCollection} 以避免与 {@code java.util.Collection} 冲突。
 */
@Entity
@Table(name = "collections")
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class PaperCollection {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "name", nullable = false)
    private String name;

    @Column(name = "description")
    private String description;

    @Column(name = "paper_count")
    private Integer paperCount;

    @Column(name = "created_at", insertable = false, updatable = false)
    private LocalDateTime createdAt;
}
