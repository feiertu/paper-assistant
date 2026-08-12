package com.paperassistant.repository;

import com.paperassistant.entity.FetchHistory;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

/**
 * 抓取历史仓库（{@code fetch_history} 表）。
 */
public interface FetchHistoryRepository extends JpaRepository<FetchHistory, Long> {

    /**
     * 查询某用户的抓取历史，按创建时间倒序。
     */
    List<FetchHistory> findByOwnerIdOrderByCreatedAtDesc(String ownerId);

    /**
     * 统计某用户的抓取历史条数。
     */
    long countByOwnerId(String ownerId);
}
