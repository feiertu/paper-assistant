package com.paperassistant.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.paperassistant.config.AppConfig;
import com.paperassistant.entity.Citation;
import com.paperassistant.entity.Paper;
import com.paperassistant.repository.CitationRepository;
import com.paperassistant.repository.PaperRepository;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.lang.reflect.Constructor;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * Unit tests for {@link CitationService} — no Spring context, no database.
 * Exercises the pure extraction helpers (arXiv ID regex, entry splitting,
 * title heuristic) and {@code batchExtract} / {@code getGraph} with mocked
 * repositories.
 */
class CitationServiceTest {

    @TempDir
    Path tempDir;

    /** An {@link AppConfig} with the given {@code dataDir} and {@code parsedDir}. */
    private static AppConfig config(String dataDir, String parsedDir) {
        try {
            Constructor<?> ctor = AppConfig.class.getDeclaredConstructors()[0];
            Object[] args = new Object[AppConfig.class.getRecordComponents().length];
            args[0] = dataDir;   // dataDir
            args[2] = parsedDir; // parsedDir
            return (AppConfig) ctor.newInstance(args);
        } catch (ReflectiveOperationException e) {
            throw new IllegalStateException("Could not build AppConfig", e);
        }
    }

    private CitationService service(CitationRepository repo, PaperRepository paperRepo, Path parsedDir) {
        return new CitationService(repo, paperRepo, config(tempDir.resolve("data").toString(), parsedDir.toString()),
                new ObjectMapper());
    }

    // ---------- extractArxivIds ----------

    @Test
    void extractArxivIdsFindsPrefixedIds() {
        List<String> ids = CitationService.extractArxivIds("See arXiv:2301.12345 and arXiv:2101.00001v2");
        assertEquals(List.of("2101.00001v2", "2301.12345"), ids); // sorted
    }

    @Test
    void extractArxivIdsFindsUrls() {
        List<String> ids = CitationService.extractArxivIds(
                "arxiv.org/abs/2301.12345 and arxiv.org/pdf/2101.00001v2");
        assertEquals(List.of("2101.00001v2", "2301.12345"), ids);
    }

    @Test
    void extractArxivIdsFindsBareIdsAndDedups() {
        List<String> ids = CitationService.extractArxivIds("paper 2301.12345 and arXiv:2301.12345");
        assertEquals(List.of("2301.12345"), ids);
    }

    @Test
    void extractArxivIdsIgnoresNonMatchingText() {
        assertTrue(CitationService.extractArxivIds("no arxiv references here 12345").isEmpty());
    }

    // ---------- splitReferenceEntries ----------

    @Test
    void splitReferenceEntriesSplitsOnNumberedEntries() {
        String text = "[1] First entry long enough to count\n[2] Second entry long enough to count";
        List<String> parts = CitationService.splitReferenceEntries(text);
        assertEquals(2, parts.size());
        assertTrue(parts.get(0).startsWith("[1]"));
        assertTrue(parts.get(1).startsWith("[2]"));
    }

    @Test
    void splitReferenceEntriesFallsBackToDoubleNewline() {
        String text = "Unnumbered first entry that is long enough\n\nUnnumbered second entry too";
        List<String> parts = CitationService.splitReferenceEntries(text);
        assertEquals(2, parts.size());
    }

    @Test
    void splitReferenceEntriesDropsTooShortParts() {
        List<String> parts = CitationService.splitReferenceEntries("[1] tiny\n[2] another entry here");
        // only the second part exceeds 20 chars
        assertEquals(1, parts.size());
        assertTrue(parts.get(0).startsWith("[2]"));
    }

    // ---------- extractTitleFromEntry / stripVersion ----------

    @Test
    void extractTitleFromEntryStripsNumberingAndAuthors() {
        String title = CitationService.extractTitleFromEntry(
                "[1] Vaswani, A., et al. (2023). Attention is all you need. arXiv:2301.12345");
        assertFalse(title.isBlank());
        assertTrue(title.length() <= 200);
    }

    @Test
    void stripVersionRemovesVersionSuffix() {
        assertEquals("2301.12345", CitationService.stripVersion("2301.12345v2"));
        assertEquals("2301.12345", CitationService.stripVersion("2301.12345"));
    }

    // ---------- batchExtract ----------

    @Test
    void batchExtractWalksParsedDirAndInsertsReferences() throws Exception {
        Path parsedDir = tempDir.resolve("parsed");
        Files.createDirectories(parsedDir);
        Files.writeString(parsedDir.resolve("2606.13673.json"), """
                {"metadata":{"title":"A Paper"},
                 "sections":[
                   {"title":"Introduction","content":"Some intro.","subsections":[]},
                   {"title":"References","content":"[1] Vaswani, A., et al. (2023). Attention is all you need. arXiv:2301.12345\\n[2] Brown, T. (2022). Language models. arxiv.org/abs/2101.00001v2","subsections":[]}
                 ]}
                """);

        CitationRepository repo = mock(CitationRepository.class);
        PaperRepository paperRepo = mock(PaperRepository.class);
        when(repo.countByCitingArxivIdAndCitedArxivId(anyString(), anyString())).thenReturn(0L);

        Map<String, Object> result = service(repo, paperRepo, parsedDir).batchExtract(null);

        assertEquals(1, result.get("processed"));
        assertEquals(2, result.get("citations"));
        verify(repo, times(2)).save(any(Citation.class));
    }

    @Test
    void batchExtractSkipsAlreadyExistingPairs() throws Exception {
        Path parsedDir = tempDir.resolve("parsed");
        Files.createDirectories(parsedDir);
        Files.writeString(parsedDir.resolve("2606.13673.json"), """
                {"sections":[{"title":"References","content":"[1] First author. (2023). A title here. arXiv:2301.12345","subsections":[]}]}
                """);

        CitationRepository repo = mock(CitationRepository.class);
        PaperRepository paperRepo = mock(PaperRepository.class);
        when(repo.countByCitingArxivIdAndCitedArxivId(anyString(), anyString())).thenReturn(1L);

        Map<String, Object> result = service(repo, paperRepo, parsedDir).batchExtract(null);

        assertEquals(0, result.get("citations"));
        verify(repo, times(0)).save(any(Citation.class));
    }

    @Test
    void batchExtractExcludesSelfCitations() throws Exception {
        Path parsedDir = tempDir.resolve("parsed");
        Files.createDirectories(parsedDir);
        // reference points at the paper's own base ID (with a version suffix) → excluded
        Files.writeString(parsedDir.resolve("2606.13673.json"), """
                {"sections":[{"title":"References","content":"[1] Self reference. (2023). About itself. arXiv:2606.13673v1","subsections":[]}]}
                """);

        CitationRepository repo = mock(CitationRepository.class);
        PaperRepository paperRepo = mock(PaperRepository.class);

        Map<String, Object> result = service(repo, paperRepo, parsedDir).batchExtract(null);

        assertEquals(0, result.get("citations"));
        verify(repo, times(0)).save(any(Citation.class));
    }

    @Test
    void batchExtractReturnsErrorWhenParsedDirMissing() {
        CitationRepository repo = mock(CitationRepository.class);
        PaperRepository paperRepo = mock(PaperRepository.class);
        Path missing = tempDir.resolve("does-not-exist");
        Map<String, Object> result = service(repo, paperRepo, missing).batchExtract(null);
        assertEquals(0, result.get("processed"));
        assertEquals(0, result.get("citations"));
        assertTrue(result.containsKey("error"));
    }

    // ---------- getGraph ----------

    @Test
    void getGraphReturnsOutgoingAndIncomingWithInDbFlag() {
        CitationRepository repo = mock(CitationRepository.class);
        PaperRepository paperRepo = mock(PaperRepository.class);

        Citation outgoing = Citation.builder()
                .id(1L).citingArxivId("2301.00001").citedArxivId("2301.12345")
                .citedTitle("Extracted title").context("ctx1").build();
        Citation incoming = Citation.builder()
                .id(2L).citingArxivId("9999.99999").citedArxivId("2301.00001")
                .citedTitle("").context("").build();

        when(repo.findByCitingArxivId("2301.00001")).thenReturn(List.of(outgoing));
        when(repo.findByCitedArxivId("2301.00001")).thenReturn(List.of(incoming));
        when(paperRepo.findByArxivId("2301.12345"))
                .thenReturn(Optional.of(Paper.builder().arxivId("2301.12345").title("DB title").build()));
        when(paperRepo.findByArxivId("9999.99999")).thenReturn(Optional.empty());

        Map<String, Object> graph = service(repo, paperRepo, tempDir).getGraph("2301.00001");

        assertEquals("2301.00001", graph.get("arxiv_id"));

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> cites = (List<Map<String, Object>>) graph.get("cites");
        assertEquals(1, cites.size());
        assertEquals("2301.12345", cites.get(0).get("cited_arxiv_id"));
        assertEquals("Extracted title", cites.get(0).get("cited_title"));
        assertEquals("ctx1", cites.get(0).get("context"));
        assertEquals(true, cites.get(0).get("in_db"));

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> citedBy = (List<Map<String, Object>>) graph.get("cited_by");
        assertEquals(1, citedBy.size());
        assertEquals("9999.99999", citedBy.get(0).get("citing_arxiv_id"));
        // 未入库 → citing_title 回退为 citing_arxiv_id 本身（Python 行为）
        assertEquals("9999.99999", citedBy.get(0).get("citing_title"));
        assertEquals(false, citedBy.get(0).get("in_db"));
    }
}
