package com.paperassistant.service;

import java.util.List;
import java.util.Map;

/**
 * Result of {@link FetchService#fetchAndPersist(String, int, String)}.
 *
 * <p>Components serialize under the app-wide {@code SNAKE_CASE} Jackson naming
 * strategy to the exact Python contract: {@code total_found}, {@code new_count},
 * {@code skipped_papers}, {@code papers}.
 *
 * @param totalFound     number of papers the arXiv API returned for the query
 * @param newCount       number of papers not yet ingested (pre-save count; some may
 *                       be skipped downstream by {@code saveMetadataToDb} duplicate check)
 * @param skippedPapers  already-ingested papers, each {@code {"id": ..., "title": ...}}
 * @param papers         the new paper metadata dicts, or all found when nothing was new
 */
public record FetchResult(
        int totalFound,
        int newCount,
        List<Map<String, Object>> skippedPapers,
        List<Map<String, Object>> papers) {
}
