package com.paperassistant.service;

import java.util.Map;

/**
 * A single BM25 retrieval hit, mirroring the Python {@code BM25Index.search()}
 * result shape {@code {"id", "document", "score", "metadata": {}}}.
 *
 * <p>{@code score} is the raw Lucene BM25 score; {@code metadata} carries the
 * same keys Python emits — {@code bm25_score} and {@code doc_len}.
 */
public record Bm25Hit(String id, String document, double score, Map<String, Object> metadata) {
}
