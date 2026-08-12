package com.paperassistant.service;

import com.paperassistant.config.AppConfig;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Constructor;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Pure unit tests for {@link Bm25Service} — no Spring context, no database.
 * Exercises tokenization (incl. the CJK bigram path), index rebuild, BM25
 * search ranking, getScores, stats and reset.
 */
class Bm25ServiceTest {

    /** An {@link AppConfig} built from all-null args → compact constructor applies defaults. */
    private static AppConfig config() {
        try {
            Constructor<?> ctor = AppConfig.class.getDeclaredConstructors()[0];
            int n = AppConfig.class.getRecordComponents().length;
            return (AppConfig) ctor.newInstance(new Object[n]);
        } catch (ReflectiveOperationException e) {
            throw new IllegalStateException("Could not build default AppConfig", e);
        }
    }

    // ---------- Tokenization ----------

    @Test
    void tokenizeKeepsEnglishWordsLowercased() {
        List<String> tokens = Bm25Service.tokenizeText("Attention Mechanism for Transformers");
        assertEquals(List.of("attention", "mechanism", "for", "transformers"), tokens);
    }

    @Test
    void tokenizeProducesCjkBigrams() {
        // "deep learning" in Chinese — CJKBigramFilter default emits overlapping bigrams.
        List<String> tokens = Bm25Service.tokenizeText("深度学习");
        assertFalse(tokens.isEmpty());
        // A 4-char CJK run yields 3 overlapping bigrams.
        assertEquals(3, tokens.size());
        assertEquals("深度", tokens.get(0));
        assertEquals("学习", tokens.get(2));
    }

    @Test
    void tokenizeHandlesMixedChineseEnglish() {
        List<String> tokens = Bm25Service.tokenizeText("attention 注意力");
        assertFalse(tokens.isEmpty());
        assertTrue(tokens.contains("attention"));
        // 3-char CJK run → 2 bigrams.
        assertTrue(tokens.contains("注意") && tokens.contains("意力"));
    }

    // ---------- Index + search ----------

    @Test
    void indexRebuildsAndSearchRanksByBm25() {
        try (Bm25Service svc = new Bm25Service(config())) {
            svc.index(
                    List.of(
                            "Transformer models for attention mechanism",
                            "A study on gradient descent optimization",
                            "Attention is all you need for deep learning"),
                    List.of("doc1", "doc2", "doc3"));

            assertEquals(3, svc.size());
            assertEquals(3, svc.stats().get("doc_count"));
            // 17 unique lowercased tokens across the three docs.
            assertEquals(17, svc.stats().get("vocab_size"));

            List<Bm25Hit> hits = svc.search("attention mechanism", 2);
            assertEquals(2, hits.size());
            // doc1 has both query terms, doc3 has one → doc1 outranks doc3.
            assertEquals("doc1", hits.get(0).id());
            assertNotEquals("doc2", hits.get(0).id()); // doc2 shares no query term
            assertTrue(hits.get(0).score() > hits.get(1).score());
            // metadata mirrors Python: bm25_score + doc_len
            assertEquals("Transformer models for attention mechanism", hits.get(0).document());
            assertTrue(hits.get(0).metadata().containsKey("bm25_score"));
            assertTrue(hits.get(0).metadata().containsKey("doc_len"));
            assertEquals(5, ((Number) hits.get(0).metadata().get("doc_len")).intValue());
        }
    }

    @Test
    void searchMatchesChineseQueryAgainstChineseDoc() {
        try (Bm25Service svc = new Bm25Service(config())) {
            svc.index(List.of("基于深度学习的文本分类方法", "image generation with diffusion models"),
                    List.of("cn", "en"));
            List<Bm25Hit> hits = svc.search("深度学习", 5);
            assertFalse(hits.isEmpty());
            assertEquals("cn", hits.get(0).id());
        }
    }

    @Test
    void searchEmptyIndexAndBlankQueryReturnEmpty() {
        try (Bm25Service svc = new Bm25Service(config())) {
            assertEquals(List.of(), svc.search("anything", 5));
            assertEquals(List.of(), svc.search("", 5));
            assertEquals(List.of(), svc.search(null, 5));
        }
    }

    @Test
    void rebuildReplacesPreviousIndex() {
        try (Bm25Service svc = new Bm25Service(config())) {
            svc.index(List.of("first document"), List.of("a"));
            assertEquals(1, svc.size());
            svc.index(List.of("second document", "third document"), List.of("b", "c"));
            assertEquals(2, svc.size());
            List<Bm25Hit> hits = svc.search("first", 5);
            assertTrue(hits.isEmpty(), "old doc must be gone after rebuild");
        }
    }

    // ---------- getScores / stats / reset ----------

    @Test
    void getScoresReturnsOneValuePerDocInIndexOrder() {
        try (Bm25Service svc = new Bm25Service(config())) {
            svc.index(List.of("attention transformer", "random unrelated text"), List.of("d1", "d2"));
            List<Float> scores = svc.getScores("attention");
            assertEquals(2, scores.size());
            assertTrue(scores.get(0) > 0.0f);   // d1 matches "attention"
            assertEquals(0.0f, scores.get(1));  // d2 has no overlap
            // Empty / null query → all zeros.
            assertEquals(List.of(0.0f, 0.0f), svc.getScores(""));
        }
    }

    @Test
    void getScoresStaysAlignedAfterRebuild() {
        try (Bm25Service svc = new Bm25Service(config())) {
            svc.index(List.of("old content"), List.of("old"));
            // Rebuild replaces the index; Lucene doc ids no longer equal corpus
            // positions after deleteAll(), so getScores must map by stored id.
            svc.index(List.of("attention transformer", "random unrelated text"), List.of("d1", "d2"));
            List<Float> scores = svc.getScores("attention");
            assertEquals(2, scores.size());
            assertTrue(scores.get(0) > 0.0f);
            assertEquals(0.0f, scores.get(1));
        }
    }

    @Test
    void statsAndReset() {
        try (Bm25Service svc = new Bm25Service(config())) {
            svc.index(List.of("attention is all you need", "attention and transformers"), List.of("x", "y"));
            Map<String, Object> stats = svc.stats();
            assertEquals(2, stats.get("doc_count"));
            assertEquals(8, ((Number) stats.get("total_tokens")).longValue()); // 5 + 3 tokens
            assertEquals(7, stats.get("vocab_size")); // attention, is, all, you, need, and, transformers
            assertTrue(((Number) stats.get("avg_doc_len")).doubleValue() == 4.0);

            svc.reset();
            assertEquals(0, svc.size());
            assertEquals(0, svc.stats().get("doc_count"));
            assertEquals(0, svc.stats().get("vocab_size"));
            assertEquals(List.of(), svc.search("attention", 5));
        }
    }
}
