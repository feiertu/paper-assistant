package com.paperassistant.service;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.paperassistant.config.AppConfig;
import org.apache.pdfbox.Loader;
import org.apache.pdfbox.cos.COSName;
import org.apache.pdfbox.pdmodel.PDDocument;
import org.apache.pdfbox.pdmodel.PDDocumentInformation;
import org.apache.pdfbox.text.PDFTextStripper;
import org.apache.pdfbox.text.TextPosition;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.io.StringWriter;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;
import java.util.stream.Stream;

/**
 * PDF parser mirroring the Python {@code src/parse/pdf.py} {@code parse_pdf_structure()}.
 *
 * <p>Pipeline: {@link PDDocument} is loaded with PDFBox, then a {@link PDFTextStripper}
 * subclass captures the text PDFBox already groups into lines ({@code writeString} /
 * {@code writeLineSeparator}), and a font-size + numbering heuristic decides which lines
 * are section / subsection headings — the same rules the Python port uses:
 *
 * <ul>
 *   <li>{@code is_section_title}: a numbered line {@code ^\d+\.|[A-Z]\.} OR a
 *       {@link #isSpecialSection special section} word rendered at {@code >= 10pt};</li>
 *   <li>{@code is_subsection_title}: {@code ^\d+\.\d+\.|[A-Z]\.\d+\.};</li>
 *   <li>lines below {@link AppConfig#pdfMinBodySize()} (default 6.5pt) are dropped as
 *       headers/footers;</li>
 *   <li>text before the first recognized heading becomes a leading "Abstract" (or
 *       "Preamble" when the document carries no title) section.</li>
 * </ul>
 *
 * <p>The result is a {@link ParsedDocument} record whose sections serialize to the same
 * JSON shape Python emits (metadata + sections with {@code title/page/size/content} and an
 * optional {@code subsections} list), so the parsed {@code .json} files written by
 * {@link #batchParse} stay compatible with the rest of the pipeline.
 */
@Service
public class ParseService {

    private static final Logger log = LoggerFactory.getLogger(ParseService.class);

    /** Longest line that can be a section heading (matches Python {@code MAX_TITLE_LEN}). */
    public static final int MAX_TITLE_LEN = 120;

    /** Special-section words are only headings when the line is at least this big (Python 10.0). */
    public static final double SPECIAL_SECTION_MIN_SIZE = 10.0;

    /** Default body-text floor when {@code paper-assistant.pdf-min-body-size} is unset (Python 6.5). */
    public static final double DEFAULT_MIN_BODY_SIZE = 6.5;

    private static final Set<String> SPECIAL_SECTIONS = Set.of(
            "references", "abstract", "acknowledgements", "acknowledgments",
            "conclusion", "conclusions", "supplementary material",
            "contents", "introduction", "related work", "related works",
            "background", "method", "methods", "methodology",
            "experiments", "experiment", "results", "discussion",
            "limitations", "appendix", "appendices");

    private static final Pattern PURE_NUM_RE = Pattern.compile("^\\d+(\\.\\d+)?\\.?\\s*$");
    private static final Pattern YEAR_RE = Pattern.compile("^(19|20)\\d{2}[a-z]?\\.?$");
    private static final Pattern CITATION_PAGE_RE =
            Pattern.compile("\\.{3,}|\\bpp?\\.\\s*\\d|\\bvol\\.?\\s*\\d|^\\s*\\d+\\s*$");
    private static final Pattern SECTION_PATTERN = Pattern.compile("^(\\d+\\.|[A-Z]\\.)\\s*\\S");
    private static final Pattern SUBSECTION_PATTERN = Pattern.compile("^(\\d+\\.\\d+\\.|[A-Z]\\.\\d+\\.)\\s*\\S");

    private final AppConfig appConfig;
    private final ObjectMapper objectMapper;

    public ParseService(AppConfig appConfig, ObjectMapper objectMapper) {
        this.appConfig = appConfig;
        this.objectMapper = objectMapper;
    }

    // ---------------------------------------------------------------------
    // Public API
    // ---------------------------------------------------------------------

    /** Parses {@code pdfPath} using the configured {@code pdf-min-body-size}. */
    public ParsedDocument parsePdf(Path pdfPath) throws IOException {
        return parsePdf(pdfPath, minBodySize());
    }

    /**
     * Parses {@code pdfPath} into a {@link ParsedDocument}.
     *
     * @param minBodySize lines below this font size are dropped (headers/footers)
     * @throws IOException if the file is missing/unreadable or PDFBox fails
     */
    public ParsedDocument parsePdf(Path pdfPath, double minBodySize) throws IOException {
        if (pdfPath == null || !Files.isRegularFile(pdfPath)) {
            throw new IOException("PDF not found: " + pdfPath);
        }
        try (PDDocument doc = Loader.loadPDF(pdfPath.toFile())) {
            Map<String, String> metadata = extractMetadata(doc);

            LineStripper stripper = new LineStripper();
            stripper.writeText(doc, new StringWriter());

            ParseState state = new ParseState();
            for (int pageIndex = 0; pageIndex < stripper.linesByPage.size(); pageIndex++) {
                int pageNo = pageIndex + 1;
                for (Line line : stripper.linesByPage.get(pageIndex)) {
                    String text = line.text.strip();
                    if (text.isEmpty()) {
                        continue;
                    }
                    double size = line.size;

                    if (isSectionTitle(text, size)) {
                        state.saveCurrentSubsection();
                        state.saveCurrentSection();
                        state.currentSection = new ParsedSection(text, pageNo, size, "", null);
                        state.currentSubsection = null;
                    } else if (isSubsectionTitle(text, size)) {
                        if (state.currentSection != null) {
                            state.saveCurrentSubsection();
                            state.currentSubsection = new ParsedSection(text, pageNo, size, "", null);
                        } else {
                            // A subsection before any section (rare): treat as pre-section text.
                            state.preSectionBuffer.add(text);
                            state.preSectionPage = pageNo;
                        }
                    } else {
                        if (size < minBodySize) {
                            continue;
                        }
                        if (state.currentSubsection != null) {
                            state.currentSubsection = appendContent(state.currentSubsection, text);
                        } else if (state.currentSection != null) {
                            state.currentSection = appendContent(state.currentSection, text);
                        } else {
                            state.preSectionBuffer.add(text);
                            if (state.preSectionPage == null) {
                                state.preSectionPage = pageNo;
                            }
                        }
                    }
                }
            }

            // Save whatever section was still open at the end of the document.
            state.saveCurrentSubsection();
            state.saveCurrentSection();

            // Text accumulated before any recognized heading becomes the leading section,
            // titled "Abstract" when the document has a title, else "Preamble" (Python parity).
            if (!state.preSectionBuffer.isEmpty()) {
                String title = hasText(metadata.get("title")) ? "Abstract" : "Preamble";
                ParsedSection preamble = new ParsedSection(
                        title,
                        state.preSectionPage == null ? 1 : state.preSectionPage,
                        0.0,
                        String.join(" ", state.preSectionBuffer),
                        null);
                state.sections.add(0, preamble);
            }

            return new ParsedDocument(metadata, state.sections);
        }
    }

    /**
     * Parses every {@code *.pdf} under {@code inputDir} (recursively) and writes one
     * {@code .json} per file under {@code outputDir}, mirroring the directory structure.
     * Per-file failures are logged and counted, never aborting the batch.
     *
     * @return the number of successfully / failed parses
     * @throws IOException if {@code inputDir} does not exist or the output dir cannot be created
     */
    public BatchParseResult batchParse(Path inputDir, Path outputDir) throws IOException {
        if (inputDir == null || !Files.isDirectory(inputDir)) {
            throw new IOException("Input directory not found: " + inputDir);
        }
        Files.createDirectories(outputDir);

        List<Path> pdfs;
        try (Stream<Path> walk = Files.walk(inputDir)) {
            pdfs = walk.filter(Files::isRegularFile)
                    .filter(p -> p.getFileName().toString().toLowerCase(Locale.ROOT).endsWith(".pdf"))
                    .sorted()
                    .toList();
        }

        if (pdfs.isEmpty()) {
            log.warn("[ParseService] No PDF files found under {}", inputDir);
            return new BatchParseResult(0, 0);
        }

        log.info("[ParseService] Batch parsing {} PDF(s): {} -> {}", pdfs.size(), inputDir, outputDir);

        int success = 0;
        int fail = 0;
        for (Path pdf : pdfs) {
            try {
                log.info("[ParseService] Parsing {}", pdf.getFileName());
                ParsedDocument doc = parsePdf(pdf);

                Path relative = inputDir.relativize(pdf);
                String jsonName = relative.getFileName().toString().replaceAll("(?i)\\.pdf$", "") + ".json";
                Path out = outputDir.resolve(relative.resolveSibling(jsonName));
                Files.createDirectories(out.getParent());
                objectMapper.writerWithDefaultPrettyPrinter().writeValue(out.toFile(), doc);

                log.info("[ParseService] Parsed {} -> {} sections, saved to {}", pdf.getFileName(),
                        doc.sections().size(), out);
                success++;
            } catch (Exception e) {
                log.error("[ParseService] Failed to parse {}: {}", pdf.getFileName(), e.getMessage(), e);
                fail++;
            }
        }

        log.info("[ParseService] Batch complete: {} success, {} failed", success, fail);
        return new BatchParseResult(success, fail);
    }

    // ---------------------------------------------------------------------
    // Heading-detection helpers (public static for direct unit testing)
    // ---------------------------------------------------------------------

    /** True when {@code text} (case-insensitive) is one of the known special-section words. */
    public static boolean isSpecialSection(String text) {
        return SPECIAL_SECTIONS.contains(text.strip().toLowerCase(Locale.ROOT));
    }

    /** Python {@code is_section_title}: numbered heading OR special-section word at >= 10pt. */
    public static boolean isSectionTitle(String text, double fontSize) {
        String t = text.strip();
        if (!looksLikeTitle(t)) {
            return false;
        }
        boolean special = isSpecialSection(t) && fontSize >= SPECIAL_SECTION_MIN_SIZE;
        return SECTION_PATTERN.matcher(t).find() || special;
    }

    /** Python {@code is_subsection_title}: {@code ^\d+\.\d+\.} or {@code ^[A-Z]\.\d+\.}. */
    public static boolean isSubsectionTitle(String text, double fontSize) {
        String t = text.strip();
        if (!looksLikeTitle(t)) {
            return false;
        }
        return SUBSECTION_PATTERN.matcher(t).find();
    }

    /**
     * Python {@code _looks_like_title}: rejects pure numbers, year-led references entries,
     * and long table-of-contents / citation-page lines.
     */
    private static boolean looksLikeTitle(String t) {
        if (t.isEmpty() || t.length() > MAX_TITLE_LEN) {
            return false;
        }
        if (PURE_NUM_RE.matcher(t).matches()) {
            return false;
        }
        String[] tokens = t.split("\\s+");
        if (tokens.length > 0) {
            // Python: first_token.rstrip('.')
            String first = tokens[0].replaceAll("\\.+$", "");
            if (YEAR_RE.matcher(first).matches()) {
                return false;
            }
        }
        return !(CITATION_PAGE_RE.matcher(t).find() && t.length() > 50);
    }

    // ---------------------------------------------------------------------
    // Internals
    // ---------------------------------------------------------------------

    private double minBodySize() {
        Double v = appConfig.pdfMinBodySize();
        return v == null ? DEFAULT_MIN_BODY_SIZE : v;
    }

    private static boolean hasText(String s) {
        return s != null && !s.isBlank();
    }

    private static Map<String, String> extractMetadata(PDDocument doc) {
        PDDocumentInformation info = doc.getDocumentInformation();
        Map<String, String> metadata = new LinkedHashMap<>();
        metadata.put("title", info.getTitle());
        metadata.put("author", info.getAuthor());
        // Raw PDF date string (e.g. "D:20260526222651-07'00'") — pymupdf returns "" when absent.
        String creationDate = info.getCOSObject().getString(COSName.CREATION_DATE);
        metadata.put("creationDate", creationDate != null ? creationDate : "");
        return metadata;
    }

    /** Immutably appends a content line to a section (Python: {@code content += " " + text}). */
    private static ParsedSection appendContent(ParsedSection section, String text) {
        return new ParsedSection(section.title(), section.page(), section.fontSize(),
                section.content() + " " + text, section.subsections());
    }

    /** Mutable state threaded through {@link #parsePdf(Path, double)}. */
    private static final class ParseState {
        ParsedSection currentSection;
        ParsedSection currentSubsection;
        final List<ParsedSection> sections = new ArrayList<>();
        final List<String> preSectionBuffer = new ArrayList<>();
        Integer preSectionPage;

        /** Python {@code save_current_subsection}: fold the open subsection into its section. */
        void saveCurrentSubsection() {
            if (currentSection != null && currentSubsection != null
                    && !currentSubsection.content().isBlank()) {
                List<ParsedSection> subs = new ArrayList<>();
                if (currentSection.subsections() != null) {
                    subs.addAll(currentSection.subsections());
                }
                subs.add(currentSubsection);
                currentSection = new ParsedSection(currentSection.title(), currentSection.page(),
                        currentSection.fontSize(), currentSection.content(), subs);
            }
            currentSubsection = null;
        }

        /** Python {@code save_current_section}: keep only sections with body content. */
        void saveCurrentSection() {
            if (currentSection != null && !currentSection.content().isBlank()) {
                sections.add(currentSection);
            }
            currentSection = null;
        }
    }

    // ---------------------------------------------------------------------
    // PDFBox line extraction
    // ---------------------------------------------------------------------

    /**
     * Reuses PDFBox's own line detection. {@code writeString} is invoked once per word with
     * its {@link TextPosition}s and {@code writeLineSeparator} after every line, so we can
     * rebuild the page's lines exactly as PDFBox's {@code getText()} would, while also
     * capturing each line's font size (first word's first character — Python's "first span
     * size"). Pages are kept separate so headings can record their page number.
     */
    private static final class LineStripper extends PDFTextStripper {

        final List<List<Line>> linesByPage = new ArrayList<>();
        private final StringBuilder currentLine = new StringBuilder();
        private Double currentLineSize;

        private LineStripper() throws IOException {
            setSortByPosition(true);
            // The assembled text is written to a discarded writer; we only consume
            // the per-word writeString / per-line writeLineSeparator callbacks.
        }

        @Override
        protected void startPage(org.apache.pdfbox.pdmodel.PDPage page) throws IOException {
            super.startPage(page);
            linesByPage.add(new ArrayList<>());
        }

        @Override
        protected void writeString(String text, List<TextPosition> textPositions) throws IOException {
            if (currentLineSize == null && textPositions != null && !textPositions.isEmpty()) {
                currentLineSize = (double) textPositions.get(0).getFontSizeInPt();
            }
            currentLine.append(text);
        }

        @Override
        protected void writeWordSeparator() throws IOException {
            // PDFBox calls this between words on the same line; without it, every
            // word would concatenate (e.g. "1.Introduction" instead of "1. Introduction").
            currentLine.append(getWordSeparator());
        }

        @Override
        protected void writeLineSeparator() throws IOException {
            if (currentLine.length() > 0) {
                List<Line> pageLines = linesByPage.get(linesByPage.size() - 1);
                pageLines.add(new Line(currentLine.toString(), currentLineSize == null ? 0.0 : currentLineSize));
            }
            currentLine.setLength(0);
            currentLineSize = null;
        }
    }

    /** A single extracted text line: text + the font size of its first character. */
    private static final class Line {
        final String text;
        final double size;

        Line(String text, double size) {
            this.text = text;
            this.size = size;
        }
    }

    // ---------------------------------------------------------------------
    // Records
    // ---------------------------------------------------------------------

    /**
     * A section (or subsection) of a parsed document.
     *
     * @param title      heading text as it appears in the PDF
     * @param page       1-based page where the heading starts
     * @param fontSize   font size of the heading line (pt); 0.0 for the synthetic preamble
     * @param content    concatenated body text (" " separated, Python-style)
     * @param subsections nested subsections, or {@code null} when there are none
     */
    public record ParsedSection(
            String title,
            int page,
            @JsonProperty("size") double fontSize,
            String content,
            @JsonInclude(JsonInclude.Include.NON_NULL) List<ParsedSection> subsections) {
    }

    /** A parsed document: metadata (title/author/creationDate) + ordered section tree. */
    public record ParsedDocument(Map<String, String> metadata, List<ParsedSection> sections) {
    }

    /** Aggregate result of {@link #batchParse(Path, Path)}. */
    public record BatchParseResult(int success, int fail) {

        /** Total number of files attempted. */
        public int total() {
            return success + fail;
        }
    }
}
