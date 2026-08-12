package com.paperassistant.repository;

import com.paperassistant.entity.Paper;
import com.paperassistant.entity.PaperCollection;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;

/**
 * 论文收藏夹仓库（{@code collections} 表）。
 *
 * <p>收藏夹与论文通过连接表 {@code collection_papers} 关联（SQL 表，无 JPA 实体），
 * 因此查询收藏夹内的论文走原生 SQL join。注意：{@code collections} 表没有
 * {@code owner_id} 列，收藏夹不区分所有者。
 */
public interface CollectionRepository extends JpaRepository<PaperCollection, Long> {

    /**
     * 查询某收藏夹内的论文（通过 {@code collection_papers} 连接表 join {@code papers}），
     * 按创建时间倒序。
     */
    @Query(value = """
        SELECT p.* FROM papers p
        INNER JOIN collection_papers cp ON cp.paper_id = p.id
        WHERE cp.collection_id = :collectionId AND p.owner_id = :ownerId
        ORDER BY p.created_at DESC
        """, nativeQuery = true)
    List<Paper> findPapersByCollectionId(@Param("collectionId") Long collectionId,
        @Param("ownerId") String ownerId);

    /**
     * 统计某收藏夹内的论文数量（用于维护 {@code collections.paper_count}）。
     */
    @Query(value = "SELECT COUNT(*) FROM collection_papers WHERE collection_id = :collectionId", nativeQuery = true)
    long countPapersByCollectionId(@Param("collectionId") Long collectionId);
}
