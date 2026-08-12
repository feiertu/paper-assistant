package com.paperassistant.repository;

import com.paperassistant.entity.QueryRecord;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

/**
 * 查询历史仓库（{@code queries} 表）。
 */
public interface QueryRecordRepository extends JpaRepository<QueryRecord, Long> {

    /**
     * 查询某用户的历史查询，按创建时间倒序。
     */
    List<QueryRecord> findByOwnerIdOrderByCreatedAtDesc(String ownerId);

    /**
     * 统计某用户的查询历史条数。
     */
    long countByOwnerId(String ownerId);

    /**
     * 删除某用户的全部查询历史（含关联的 query_papers 记录，依赖外键级联删除）。
     */
    void deleteByOwnerId(String ownerId);
}
