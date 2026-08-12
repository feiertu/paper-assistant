package com.paperassistant.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.paperassistant.config.AppConfig;
import com.paperassistant.service.ParseService.ParsedDocument;
import com.paperassistant.service.ParseService.ParsedSection;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Constructor;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

/**
 * Tests for {@link ParseService}: heading-detection heuristics (pure unit tests) plus
 * PDFBox parsing / JSON contract checks. No Spring context or database is required.
 */
class ParseServiceTest {

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

    private static ParseService service() {
        return new ParseService(config(), new ObjectMapper());
    }

    // ---------- Heading detection heuristics ----------

    @Test
    void detectsSpecialSectionsCaseInsensitively() {
        assertTrue(ParseService.isSpecialSection("References"));
        assertTrue(ParseService.isSpecialSection("  ABSTRACT  "));
        assertTrue(ParseService.isSpecialSection("related work"));
        assertFalse(ParseService.isSpecialSection("Introduction to Agents"));
    }

    @Test
    void sectionTitleMatchesNumberedPattern() {
        assertTrue(ParseService.isSectionTitle("1. Introduction", 10.0));
        assertTrue(ParseService.isSectionTitle("3.2 Results", 10.0));
        assertTrue(ParseService.isSectionTitle("A. Proof of Lemma 1", 10.0));
        assertFalse(ParseService.isSectionTitle("12 apples in a basket", 10.0));
    }

    @Test
    void sectionTitleRequiresLargeFontForSpecialWords() {
        assertTrue(ParseService.isSectionTitle("Abstract", 10.0));
        assertFalse(ParseService.isSectionTitle("Abstract", 9.5));
    }

    @Test
    void subsectionTitleMatchesDottedPattern() {
        assertTrue(ParseService.isSubsectionTitle("3.2.1 Details", 9.0));
        assertTrue(ParseService.isSubsectionTitle("A.1.2 Proof", 9.0));
        // A single-digit section number is not a subsection.
        assertFalse(ParseService.isSubsectionTitle("3.2 Results", 9.0));
    }

    @Test
    void filtersPureNumbersAndYearEntries() {
        assertFalse(ParseService.isSectionTitle("1", 14.0));
        assertFalse(ParseService.isSectionTitle("2023", 14.0));
        // A section that is just "1." (no trailing content) — still filtered by pure-number rule.
        assertFalse(ParseService.isSectionTitle("1.", 14.0));
    }

    @Test
    void filtersLongCitationPageLines() {
        // A long table-of-contents / citation line (>50 chars) is not a heading.
        String toc = "1. Introduction ...................... 3  2. Related Work ...................... 5  3. Method ...................... 9";
        assertTrue(toc.length() > 50);
        assertFalse(ParseService.isSectionTitle(toc, 11.0));
    }

    @Test
    void rejectsOverlongTitles() {
        String longTitle = "A".repeat(200);
        assertFalse(ParseService.isSectionTitle(longTitle + ". X", 14.0));
    }

    // ---------- JSON contract ----------

    @Test
    void serializesToPythonContractShape() throws Exception {
        ParsedSection subsection = new ParsedSection("3.2.1 Setup", 4, 9.0, "we ran 100 trials", null);
        ParsedSection section = new ParsedSection("3. Experiments", 4, 11.0,
                " we designed the study", List.of(subsection));
        ParsedDocument doc = new ParsedDocument(
                Map.of("title", "A Paper", "author", "Jane Doe", "creationDate", "D:20260101120000Z"),
                List.of(section));

        // Plain mapper: keys must match the Python JSON contract.
        String json = new ObjectMapper()
                .writerWithDefaultPrettyPrinter()
                .writeValueAsString(doc);
        assertTrue(json.contains("\"metadata\""));
        assertTrue(json.contains("\"creationDate\""));
        assertTrue(json.contains("\"size\" : 11.0"), json);
        // subsection key present, nested subsection size correct
        assertTrue(json.contains("\"subsections\""));
        assertTrue(json.contains("\"title\" : \"3.2.1 Setup\""), json);
    }

    @Test
    void omitsSubsectionsWhenEmptyUnderSnakeCaseMapper() throws Exception {
        ParsedSection bare = new ParsedSection("Abstract", 1, 12.0, " short abstract text", null);
        ParsedDocument doc = new ParsedDocument(Map.of("title", "T"), List.of(bare));

        // Mirror the app-wide SNAKE_CASE ObjectMapper; @JsonProperty("size") must win.
        ObjectMapper snake = new ObjectMapper()
                .setPropertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE)
                .configure(SerializationFeature.INDENT_OUTPUT, true);
        String json = snake.writeValueAsString(doc);
        assertTrue(json.contains("\"size\" : 12.0"), json);
        assertFalse(json.contains("font_size"), json);
        assertFalse(json.contains("subsections"), json);
    }

    // ---------- PDFBox integration (skipped when sample PDFs are absent) ----------

    @Test
    void parsesRealSamplePdf() throws Exception {
        Path pdf = Path.of("..", "data", "raw", "2606.13673v1.pdf");
        assumeTrue(Files.isRegularFile(pdf), "sample PDF not present: " + pdf.toAbsolutePath());

        ParsedDocument doc = service().parsePdf(pdf);

        assertNotNull(doc.metadata());
        assertNotNull(doc.sections());
        assertFalse(doc.sections().isEmpty(), "expected at least the preamble section");

        ParsedSection first = doc.sections().get(0);
        // Front-matter buffer becomes the leading section (Abstract when a title exists).
        assertEquals("Abstract", first.title());
        assertEquals(0.0, first.fontSize());
        assertFalse(first.content().isBlank());

        // Section bodies accumulate space-joined text.
        boolean hasSectionWithContent = doc.sections().stream()
                .anyMatch(s -> s.page() > 0 && !s.content().isBlank());
        assertTrue(hasSectionWithContent, "expected a real section with body content");
    }

    @Test
    void batchParseWritesJsonMirroringDirectoryStructure() throws Exception {
        Path samplePdf = Path.of("..", "data", "raw", "2606.13673v1.pdf");
        assumeTrue(Files.isRegularFile(samplePdf), "sample PDF not present: " + samplePdf.toAbsolutePath());

        Path input = Path.of("..", "data", "raw");
        Path output = Files.createTempDirectory("parse-batch-test");
        try {
            ParseService.BatchParseResult result = service().batchParse(input, output);

            assertTrue(result.success() >= 1, "expected at least one parsed PDF");
            assertEquals(0, result.fail());

            // Output preserves the relative filename with .json suffix.
            Path expected = output.resolve("2606.13673v1.json");
            assertTrue(Files.isRegularFile(expected), "expected JSON at " + expected);
            String json = Files.readString(expected);
            assertTrue(json.contains("\"sections\""));
            assertTrue(json.contains("\"metadata\""));
        } finally {
            deleteRecursively(output);
        }
    }

    // ---------- helpers ----------

    private static void deleteRecursively(Path root) throws Exception {
        if (!Files.exists(root)) {
            return;
        }
        try (var walk = Files.walk(root)) {
            walk.sorted(java.util.Comparator.reverseOrder()).forEach(p -> {
                try {
                    Files.deleteIfExists(p);
                } catch (java.io.IOException ignored) {
                    // best-effort cleanup
                }
            });
        }
    }
}
