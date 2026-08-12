package com.paperassistant.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.paperassistant.config.AppConfig;
import com.paperassistant.entity.Paper;
import com.paperassistant.repository.PaperRepository;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.web.reactive.function.client.WebClient;

import java.lang.reflect.Constructor;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * Tests for {@link FetchService}: Atom XML parsing / extraction (pure static
 * unit tests) plus {@code saveMetadataToDb} and {@code partitionPapers} with a
 * mocked {@link PaperRepository}. No Spring context, no network.
 */
class FetchServiceTest {

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

    private static FetchService service(PaperRepository repo) {
        return new FetchService(WebClient.builder(), repo, config());
    }

    /** A paper dict matching the Python {@code fetch_arxiv_metadata} contract. */
    private static Map<String, Object> paper(String id, String title, String summary, String cat) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", id);
        m.put("title", title);
        m.put("authors", "Alice Smith, Bob Jones");
        m.put("summary", summary);
        m.put("published", "2023-01-01T00:00:00Z");
        m.put("pdf_url", "http://arxiv.org/pdf/" + id);
        m.put("categories", List.of(cat));
        m.put("primary_category", cat);
        return m;
    }

    // ---------- Atom XML parsing / extraction ----------

    @Test
    void parseArxivXmlParsesRealisticAtomFeed() {
        String xml = String.format("""
                <?xml version="1.0" encoding="UTF-8"?>
                <feed xmlns="http://www.w3.org/2005/Atom">
                  <entry>
                    <id>http://arxiv.org/abs/2301.00001v2</id>
                    <published>2023-01-01T00:00:00Z</published>
                    <title>%s</title>
                    <summary>This is the abstract of the paper with some line breaks.</summary>
                    <author><name>Alice Smith</name></author>
                    <author><name>Bob Jones</name></author>
                    <category term="cs.AI"/>
                    <category term="stat.ML"/>
                    <link href="http://arxiv.org/abs/2301.00001v2" rel="alternate" type="text/html"/>
                    <link title="pdf" href="http://arxiv.org/pdf/2301.00001v2" rel="related" type="application/pdf"/>
                  </entry>
                  <entry>
                    <id>http://arxiv.org/abs/2302.00002v1</id>
                    <published>2023-02-01T00:00:00Z</published>
                    <title>Second Paper</title>
                    <summary>No PDF link here.</summary>
                    <author><name>Carol</name></author>
                    <category term="cs.LG"/>
                    <link href="http://arxiv.org/abs/2302.00002v1" rel="alternate" type="text/html"/>
                  </entry>
                </feed>
                """, "A Paper on Learning\nWith Newlines");

        List<Map<String, Object>> papers = FetchService.parseArxivXml(xml);
        assertEquals(2, papers.size());

        Map<String, Object> p1 = papers.get(0);
        assertEquals("2301.00001v2", p1.get("id"));
        assertEquals("A Paper on Learning With Newlines", p1.get("title"));
        assertEquals("Alice Smith, Bob Jones", p1.get("authors"));
        assertEquals("This is the abstract of the paper with some line breaks.", p1.get("summary"));
        assertEquals("2023-01-01T00:00:00Z", p1.get("published"));
        assertEquals("http://arxiv.org/pdf/2301.00001v2", p1.get("pdf_url"));
        assertEquals(List.of("cs.AI", "stat.ML"), p1.get("categories"));
        assertEquals("cs.AI", p1.get("primary_category"));

        // Second entry has no PDF link → standard arXiv fallback URL.
        Map<String, Object> p2 = papers.get(1);
        assertEquals("2302.00002v1", p2.get("id"));
        assertEquals("Second Paper", p2.get("title"));
        assertEquals("https://arxiv.org/pdf/2302.00002v1.pdf", p2.get("pdf_url"));
        assertEquals("cs.LG", p2.get("primary_category"));
    }

    @Test
    void parseArxivXmlDetectsPdfByTypeSuffixAndTitle() {
        String xml = """
                <feed xmlns="http://www.w3.org/2005/Atom">
                  <entry>
                    <id>http://arxiv.org/abs/1001.0001v1</id>
                    <title>ByType</title>
                    <link type="application/pdf" href="http://arxiv.org/pdf/1001.0001v1"/>
                  </entry>
                  <entry>
                    <id>http://arxiv.org/abs/1002.0002v1</id>
                    <title>BySuffix</title>
                    <link href="http://export.arxiv.org/pdf/1002.0002v1.pdf"/>
                  </entry>
                  <entry>
                    <id>http://arxiv.org/abs/1003.0003v1</id>
                    <title>ByTitle</title>
                    <link title="pdf" href="http://arxiv.org/pdf/1003.0003v1"/>
                  </entry>
                </feed>
                """;
        List<Map<String, Object>> papers = FetchService.parseArxivXml(xml);
        assertEquals(3, papers.size());
        assertEquals("http://arxiv.org/pdf/1001.0001v1", papers.get(0).get("pdf_url"));
        assertEquals("http://export.arxiv.org/pdf/1002.0002v1.pdf", papers.get(1).get("pdf_url"));
        assertEquals("http://arxiv.org/pdf/1003.0003v1", papers.get(2).get("pdf_url"));
    }

    @Test
    void parseArxivXmlHandlesBlankAndMalformedInput() {
        assertTrue(FetchService.parseArxivXml(null).isEmpty());
        assertTrue(FetchService.parseArxivXml("   ").isEmpty());
        assertTrue(FetchService.parseArxivXml("<not-valid").isEmpty());
        // An entry without an id is skipped, not fatal.
        assertTrue(FetchService.parseArxivXml("<feed><entry>no-id</entry></feed>").isEmpty());
    }

    @Test
    void parseArxivXmlExtractsIdFromLastUrlSegment() {
        String xml = """
                <feed xmlns="http://www.w3.org/2005/Atom">
                  <entry>
                    <id>http://arxiv.org/abs/2106.12345v3</id>
                    <title>T</title>
                    <author><name>N</name></author>
                  </entry>
                </feed>
                """;
        List<Map<String, Object>> papers = FetchService.parseArxivXml(xml);
        assertEquals(1, papers.size());
        assertEquals("2106.12345v3", papers.get(0).get("id"));
        assertEquals("", papers.get(0).get("summary"));
        assertEquals("N", papers.get(0).get("authors"));
        assertEquals("", papers.get(0).get("primary_category"));
        assertEquals("https://arxiv.org/pdf/2106.12345v3.pdf", papers.get(0).get("pdf_url"));
    }

    // ---------- partitionPapers ----------

    // ---------- FetchResult JSON contract ----------

    @Test
    void fetchResultSerializesToSnakeCaseContract() throws Exception {
        ObjectMapper snake = new ObjectMapper()
                .setPropertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE);
        Map<String, Object> skipped = new LinkedHashMap<>();
        skipped.put("id", "2301.00001v1");
        skipped.put("title", "Old Paper");
        FetchResult r = new FetchResult(5, 2, List.of(skipped),
                List.of(paper("2302.00002v1", "New Paper", "abs", "cs.AI")));

        String json = snake.writeValueAsString(r);
        assertTrue(json.contains("\"total_found\":5"), json);
        assertTrue(json.contains("\"new_count\":2"), json);
        assertTrue(json.contains("\"skipped_papers\""), json);
        assertTrue(json.contains("\"papers\""), json);
    }

    // ---------- partitionPapers ----------

    @Test
    void partitionPapersSplitsNewAndSkipped() {
        List<Map<String, Object>> papers = List.of(
                paper("a", "Paper A", "abs", "cs.AI"),
                paper("b", "Paper B", "abs", "cs.LG"),
                paper("c", "Paper C", "abs", "stat.ML"));

        FetchService.FetchPartition part = FetchService.partitionPapers(papers, Set.of("a"));

        assertEquals(2, part.newPapers().size());
        assertEquals(List.of("b", "c"), part.newPapers().stream().map(p -> p.get("id")).toList());

        assertEquals(1, part.skippedPapers().size());
        assertEquals("a", part.skippedPapers().get(0).get("id"));
        assertEquals("Paper A", part.skippedPapers().get(0).get("title"));
    }

    // ---------- saveMetadataToDb ----------

    @Test
    void saveMetadataToDbMapsFieldsAndCountsSaves() {
        PaperRepository repo = mock(PaperRepository.class);
        when(repo.findByArxivIdAndOwnerId(anyString(), anyString())).thenReturn(Optional.empty());
        FetchService svc = service(repo);

        List<Map<String, Object>> papers = List.of(
                paper("2301.00001v1", "First", "Abstract one", "cs.AI"),
                paper("2302.00002v1", "Second", "Abstract two", "stat.ML"));

        int saved = svc.saveMetadataToDb(papers, "owner-1");

        assertEquals(2, saved);
        ArgumentCaptor<Paper> captor = ArgumentCaptor.forClass(Paper.class);
        verify(repo, times(2)).save(captor.capture());

        Paper first = captor.getAllValues().get(0);
        assertEquals("2301.00001v1", first.getArxivId());
        assertEquals("First", first.getTitle());
        assertEquals("Alice Smith, Bob Jones", first.getAuthors());
        assertEquals("Abstract one", first.getAbstractText());
        assertEquals("2023-01-01T00:00:00Z", first.getPublished());
        assertEquals("http://arxiv.org/pdf/2301.00001v1", first.getPdfUrl());
        assertEquals("arxiv:cs.AI", first.getSource());
        assertEquals("pending", first.getIngestStatus());
        assertEquals(0, first.getChunkCount());
        assertEquals("owner-1", first.getOwnerId());

        Paper second = captor.getAllValues().get(1);
        assertEquals("arxiv:stat.ML", second.getSource());
    }

    @Test
    void saveMetadataToDbSkipsExistingPapers() {
        PaperRepository repo = mock(PaperRepository.class);
        when(repo.findByArxivIdAndOwnerId(eq("2301.00001v1"), anyString()))
                .thenReturn(Optional.of(new Paper()));
        when(repo.findByArxivIdAndOwnerId(eq("2302.00002v1"), anyString()))
                .thenReturn(Optional.empty());
        FetchService svc = service(repo);

        int saved = svc.saveMetadataToDb(
                List.of(paper("2301.00001v1", "First", "abs", "cs.AI"),
                        paper("2302.00002v1", "Second", "abs", "cs.LG")),
                "owner-1");

        assertEquals(1, saved);
        verify(repo, times(1)).save(any(Paper.class));
    }

    @Test
    void saveMetadataToDbSurvivesSaveFailure() {
        PaperRepository repo = mock(PaperRepository.class);
        when(repo.findByArxivIdAndOwnerId(anyString(), anyString())).thenReturn(Optional.empty());
        when(repo.save(any(Paper.class)))
                .thenThrow(new DataIntegrityViolationException("duplicate arxiv_id"));
        FetchService svc = service(repo);

        int saved = svc.saveMetadataToDb(List.of(paper("x", "X", "abs", "cs.AI")), "owner-1");

        assertEquals(0, saved);
        verify(repo, times(1)).save(any(Paper.class));
    }
}
