package com.paperassistant.service;

import com.paperassistant.config.AppConfig;
import jakarta.annotation.PreDestroy;
import org.apache.lucene.analysis.Analyzer;
import org.apache.lucene.analysis.TokenStream;
import org.apache.lucene.analysis.cjk.CJKBigramFilter;
import org.apache.lucene.analysis.core.LowerCaseFilter;
import org.apache.lucene.analysis.standard.StandardTokenizer;
import org.apache.lucene.analysis.tokenattributes.CharTermAttribute;
import org.apache.lucene.document.Document;
import org.apache.lucene.document.Field;
import org.apache.lucene.document.StoredField;
import org.apache.lucene.document.TextField;
import org.apache.lucene.index.DirectoryReader;
import org.apache.lucene.index.IndexWriter;
import org.apache.lucene.index.IndexWriterConfig;
import org.apache.lucene.index.IndexableField;
import org.apache.lucene.index.StoredFields;
import org.apache.lucene.index.Term;
import org.apache.lucene.search.BooleanClause;
import org.apache.lucene.search.BooleanQuery;
import org.apache.lucene.search.IndexSearcher;
import org.apache.lucene.search.Query;
import org.apache.lucene.search.ScoreDoc;
import org.apache.lucene.search.TermQuery;
import org.apache.lucene.search.TopDocs;
import org.apache.lucene.search.similarities.BM25Similarity;
import org.apache.lucene.store.ByteBuffersDirectory;
import org.apache.lucene.store.Directory;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Okapi BM25 sparse retrieval backed by an in-memory Apache Lucene index,
 * mirroring the Python {@code src/embed/bm25.py} ({@code BM25Index}).
 *
 * <p>Parameter parity with Python: {@code k1 = 1.5}, {@code b = 0.75}. The index
 * lives in a {@link ByteBuffersDirectory} (the modern replacement for the
 * deprecated {@code RAMDirectory}) so no disk I/O is involved.
 *
 * <p>Tokenizer pipeline: {@link StandardTokenizer} → {@link LowerCaseFilter} →
 * {@link CJKBigramFilter} — English words are kept whole and lowercased while
 * CJK runs are split into overlapping bigrams, giving bilingual retrieval.
 *
 * <p><b>Thread-safety / visibility contract.</b> {@link IndexWriter} is not
 * thread-safe and search must see the last {@link #index}ed snapshot, so every
 * public mutation and read is {@code synchronized} on the service instance.
 * Reads therefore never race a rebuild. For an in-memory index that is rebuilt
 * rarely (on ingestion) and queried at low QPS this is the pragmatic, correct
 * choice.
 *
 * <p>The document {@code id} is whatever the caller passes to {@link #index};
 * the fusion path in {@link EmbedService} expects it to equal the {@code id}
 * used by the dense (pgvector) path — i.e. the paper {@code arxivId}.
 */
@Service
public class Bm25Service implements AutoCloseable {

    private static final Logger log = LoggerFactory.getLogger(Bm25Service.class);

    /** BM25 saturation parameter (matches Python {@code BM25Index(k1=1.5)}). */
    private static final float K1 = 1.5f;
    /** BM25 length-normalization parameter (matches Python {@code b=0.75}). */
    private static final float B = 0.75f;

    /** Stored field holding the caller-supplied document id. */
    static final String ID_FIELD = "id";
    /** Analyzed + indexed BM25 field (the field the query is run against). */
    static final String TEXT_FIELD = "text";
    /** Stored field holding the original document text (returned in hits). */
    static final String DOC_FIELD = "document";
    /** Stored numeric field with the per-document token count. */
    static final String DOC_LEN_FIELD = "doc_len";

    private final AppConfig config;

    /** Shared, stateless analyzer — safe for concurrent {@code tokenStream()} use. */
    private static final Analyzer ANALYZER = createAnalyzer();
    private final Directory directory;
    private final IndexWriter writer;

    // ---- corpus stats kept in sync with the Lucene index ----
    private int docCount;
    private long totalTokens;
    private final Set<String> vocab = new HashSet<>();
    /**
     * Caller-supplied id → corpus position. Used to map Lucene results back to
     * corpus order in {@link #getScores} — Lucene's internal doc ids are NOT the
     * corpus position once a fully-deleted segment remains after
     * {@code IndexWriter.deleteAll()} + re-add.
     */
    private final Map<String, Integer> idToIndex = new HashMap<>();

    // ---- searchable snapshot (rebuilt on every index()/reset()) ----
    private DirectoryReader reader;
    private IndexSearcher searcher;

    public Bm25Service(AppConfig config) {
        this.config = config;
        this.directory = new ByteBuffersDirectory();
        IndexWriterConfig iwc = new IndexWriterConfig(ANALYZER);
        iwc.setOpenMode(IndexWriterConfig.OpenMode.CREATE);
        // k1=1.5, b=0.75 — same BM25 parameters as the Python implementation.
        iwc.setSimilarity(new BM25Similarity(K1, B));
        try {
            this.writer = new IndexWriter(directory, iwc);
        } catch (IOException e) {
            throw new IllegalStateException("Failed to initialize the in-memory BM25 index", e);
        }
        log.info("Bm25Service initialized: k1={} b={} in-memory Lucene index (empty); "
                + "rrfTopN={} rrfK={} bm25Weight={}",
                K1, B, config.rrfTopN(), config.rrfK(), config.bm25Weight());
    }

    // ---------- Indexing ----------

    /**
     * Rebuilds the whole index from {@code docs} / {@code ids} (replace, not
     * append) — same replace semantics as Python {@code BM25Index.index(..., reset=True)}.
     *
     * @param docs document texts (null text treated as empty string)
     * @param ids  per-document ids (null falls back to {@code bm25_<i>})
     * @throws IllegalArgumentException if {@code docs.size() != ids.size()}
     */
    public synchronized void index(List<String> docs, List<String> ids) {
        if (docs == null) {
            throw new IllegalArgumentException("docs must not be null");
        }
        if (ids == null) {
            throw new IllegalArgumentException("ids must not be null");
        }
        if (docs.size() != ids.size()) {
            throw new IllegalArgumentException(
                    "docs and ids must have the same size (" + docs.size() + " vs " + ids.size() + ")");
        }
        try {
            writer.deleteAll();
            docCount = 0;
            totalTokens = 0;
            vocab.clear();
            idToIndex.clear();

            for (int i = 0; i < docs.size(); i++) {
                String text = docs.get(i) == null ? "" : docs.get(i);
                String id = ids.get(i) == null ? "bm25_" + i : ids.get(i);

                List<String> tokens = tokenizeText(text);
                docCount++;
                totalTokens += tokens.size();
                vocab.addAll(tokens);
                idToIndex.put(id, i);

                Document luceneDoc = new Document();
                luceneDoc.add(new StoredField(ID_FIELD, id));
                // Tokenized + indexed (with norms, which BM25 needs) but NOT stored.
                luceneDoc.add(new TextField(TEXT_FIELD, text, Field.Store.NO));
                // Original text and length stored so search hits can return them.
                luceneDoc.add(new StoredField(DOC_FIELD, text));
                luceneDoc.add(new StoredField(DOC_LEN_FIELD, tokens.size()));
                writer.addDocument(luceneDoc);
            }
            writer.commit();

            swapReader();
        } catch (IOException e) {
            throw new IllegalStateException("Failed to rebuild the BM25 index", e);
        }
        log.info("BM25 index rebuilt: {} docs", docCount);
    }

    // ---------- Retrieval ----------

    /**
     * BM25 retrieval for {@code query}, returning the {@code topK} best hits
     * ranked by score descending. Empty query / empty index → empty list.
     */
    public synchronized List<Bm25Hit> search(String query, int topK) {
        if (searcher == null || docCount == 0 || topK <= 0) {
            return List.of();
        }
        Query q = buildQuery(query);
        if (q == null) {
            return List.of();
        }
        try {
            TopDocs topDocs = searcher.search(q, topK);
            StoredFields stored = reader.storedFields();
            List<Bm25Hit> hits = new ArrayList<>(topDocs.scoreDocs.length);
            for (ScoreDoc sd : topDocs.scoreDocs) {
                Document d = stored.document(sd.doc);
                String id = d.get(ID_FIELD);
                String document = d.get(DOC_FIELD);
                int docLen = docLenOf(d);
                Map<String, Object> metadata = new LinkedHashMap<>();
                metadata.put("bm25_score", (double) sd.score);
                metadata.put("doc_len", docLen);
                hits.add(new Bm25Hit(id, document, sd.score, metadata));
            }
            return hits;
        } catch (IOException e) {
            throw new IllegalStateException("BM25 search failed", e);
        }
    }

    /**
     * BM25 score for every indexed document, in index (corpus) order — used by
     * the RRF fusion in {@link EmbedService}. Documents sharing no term with the
     * query score 0.0, mirroring Python {@code BM25Index.get_scores()}.
     */
    public synchronized List<Float> getScores(String query) {
        if (searcher == null || docCount == 0) {
            return List.of();
        }
        Query q = buildQuery(query);
        if (q == null) {
            return Collections.nCopies(docCount, 0.0f);
        }
        try {
            TopDocs topDocs = searcher.search(q, docCount);
            StoredFields stored = reader.storedFields();
            float[] scores = new float[docCount];
            for (ScoreDoc sd : topDocs.scoreDocs) {
                // Map back to corpus position via the stored id, never via sd.doc:
                // after deleteAll()+re-add the Lucene doc ids are offset past the
                // fully-deleted segment and no longer equal the corpus position.
                Document d = stored.document(sd.doc);
                Integer idx = idToIndex.get(d.get(ID_FIELD));
                if (idx != null && idx < docCount) {
                    scores[idx] = sd.score;
                }
            }
            List<Float> result = new ArrayList<>(docCount);
            for (float s : scores) {
                result.add(s);
            }
            return result;
        } catch (IOException e) {
            throw new IllegalStateException("BM25 score computation failed", e);
        }
    }

    // ---------- Management ----------

    /** Number of indexed documents. */
    public synchronized int size() {
        return docCount;
    }

    /** Clears the index and resets all counters. */
    public synchronized void reset() {
        try {
            writer.deleteAll();
            writer.commit();
            docCount = 0;
            totalTokens = 0;
            vocab.clear();
            idToIndex.clear();
            swapReader();
        } catch (IOException e) {
            throw new IllegalStateException("Failed to reset the BM25 index", e);
        }
        log.info("BM25 index reset");
    }

    /**
     * Index statistics — {@code doc_count}, {@code vocab_size},
     * {@code avg_doc_len} (1 decimal, matching Python) and {@code total_tokens}.
     */
    public synchronized Map<String, Object> stats() {
        double avg = docCount == 0 ? 0.0 : (double) totalTokens / docCount;
        Map<String, Object> stats = new LinkedHashMap<>();
        stats.put("doc_count", docCount);
        stats.put("vocab_size", vocab.size());
        stats.put("avg_doc_len", Math.round(avg * 10.0) / 10.0);
        stats.put("total_tokens", totalTokens);
        return stats;
    }

    /** Releases the Lucene writer / directory (called on Spring shutdown). */
    @PreDestroy
    public void close() {
        try {
            if (reader != null) {
                reader.close();
            }
        } catch (IOException ignored) {
            // best-effort close
        }
        try {
            writer.close();
            directory.close();
            // ANALYZER is a shared static — never closed (closing it would poison
            // every other Bm25Service instance / future indexing).
        } catch (IOException e) {
            log.warn("Error closing BM25 index resources: {}", e.getMessage());
        }
    }

    // ---------- Internals ----------

    /** Tokenizer pipeline: Standard → LowerCase → CJK bigram (bilingual). */
    private static Analyzer createAnalyzer() {
        return new Analyzer() {
            @Override
            protected TokenStreamComponents createComponents(String fieldName) {
                StandardTokenizer src = new StandardTokenizer();
                TokenStream tok = new LowerCaseFilter(src);
                tok = new CJKBigramFilter(tok);
                return new TokenStreamComponents(src, tok);
            }
        };
    }

    /** Tokenizes a text with the same analyzer used for indexing. */
    static List<String> tokenizeText(String text) {
        List<String> tokens = new ArrayList<>();
        if (text == null || text.isEmpty()) {
            return tokens;
        }
        try (TokenStream ts = ANALYZER.tokenStream(TEXT_FIELD, text)) {
            CharTermAttribute term = ts.addAttribute(CharTermAttribute.class);
            ts.reset();
            while (ts.incrementToken()) {
                tokens.add(term.toString());
            }
            ts.end();
        } catch (IOException e) {
            throw new IllegalStateException("BM25 tokenization failed", e);
        }
        return tokens;
    }

    /** Builds a disjunction of per-term TermQueries from the analyzed query. */
    private Query buildQuery(String query) {
        if (query == null || query.isBlank()) {
            return null;
        }
        List<String> tokens = tokenizeText(query);
        if (tokens.isEmpty()) {
            return null;
        }
        BooleanQuery.Builder builder = new BooleanQuery.Builder();
        // One SHOULD clause per token occurrence (duplicates retained) so a term
        // repeated in the query contributes its BM25 weight more than once —
        // mirroring Python's _score_doc loop over every query token.
        for (String token : tokens) {
            builder.add(new TermQuery(new Term(TEXT_FIELD, token)), BooleanClause.Occur.SHOULD);
        }
        return builder.build();
    }

    /** Closes the old reader and swaps in a fresh one over the current writer. */
    private void swapReader() throws IOException {
        DirectoryReader old = this.reader;
        this.reader = DirectoryReader.open(writer);
        IndexSearcher s = new IndexSearcher(this.reader);
        // Lucene's IndexSearcher default similarity is BM25 with k1=1.2 — it MUST
        // be overridden to 1.5/0.75 or the scores (and ranks) would silently drift.
        s.setSimilarity(new BM25Similarity(K1, B));
        this.searcher = s;
        if (old != null) {
            old.close();
        }
    }

    private static int docLenOf(Document d) {
        IndexableField f = d.getField(DOC_LEN_FIELD);
        Number num = f == null ? null : f.numericValue();
        return num == null ? 0 : num.intValue();
    }
}
