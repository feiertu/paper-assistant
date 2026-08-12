package com.paperassistant.agent;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.annotation.JsonPropertyDescription;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.paperassistant.config.AppConfig;
import com.paperassistant.entity.Paper;
import com.paperassistant.llm.ChatClientService;
import com.paperassistant.llm.PromptTemplates;
import com.paperassistant.repository.PaperRepository;
import com.paperassistant.service.CitationService;
import com.paperassistant.service.RagService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * Agent tool methods exposed to the LLM for paper-related operations.
 *
 * <p>Each tool returns a String and catches all exceptions internally, returning
 * an error string. The 7 methods mirror the Python agent's 7 @tool functions.
 *
 * <p>Input record types are defined here for Spring AI {@code FunctionCallback}
 * JSON Schema auto-generation. The records use Jackson annotations so Spring AI
 * can produce OpenAI-compatible tool definitions.
 */
@Component
public class AgentTools {

    private static final Logger log = LoggerFactory.getLogger(AgentTools.class);

    private static final int MAX_TEXT_CHARS = 6000;

    private final PaperRepository paperRepository;
    private final CitationService citationService;
    private final RagService ragService;
    private final ChatClientService chatClientService;
    private final AppConfig config;
    private final ObjectMapper objectMapper;

    public AgentTools(PaperRepository paperRepository,
                      CitationService citationService,
                      RagService ragService,
                      ChatClientService chatClientService,
                      AppConfig config,
                      ObjectMapper objectMapper) {
        this.paperRepository = paperRepository;
        this.citationService = citationService;
        this.ragService = ragService;
        this.chatClientService = chatClientService;
        this.config = config;
        this.objectMapper = objectMapper;
    }

    // ──────────────────────────────────────────────
    //  Input record types (for FunctionCallback schema)
    // ──────────────────────────────────────────────

    public record SearchInput(
            @JsonProperty("query") @JsonPropertyDescription("搜索关键词或论文标题") String query,
            @JsonProperty("mode") @JsonPropertyDescription("搜索模式: fts(全文搜索), semantic(语义搜索), list(列出全部)") String mode,
            @JsonProperty("top_k") @JsonPropertyDescription("返回结果数量") int topK,
            @JsonProperty("author") @JsonPropertyDescription("按作者过滤，可选") String author,
            @JsonProperty("year_from") @JsonPropertyDescription("起始发表年份，可选") String yearFrom,
            @JsonProperty("year_to") @JsonPropertyDescription("结束发表年份，可选") String yearTo
    ) {}

    public record GetPaperInput(
            @JsonProperty("arxiv_id") @JsonPropertyDescription("论文的 arXiv ID，如 2301.12345") String arxivId
    ) {}

    public record SummarizePaperInput(
            @JsonProperty("arxiv_id") @JsonPropertyDescription("论文 arXiv ID") String arxivId,
            @JsonProperty("lang") @JsonPropertyDescription("语言: zh(中文) 或 en(英文)") String lang
    ) {}

    public record GetCitationsInput(
            @JsonProperty("arxiv_id") @JsonPropertyDescription("论文 arXiv ID") String arxivId
    ) {}

    public record ComparePapersInput(
            @JsonProperty("arxiv_id1") @JsonPropertyDescription("第一篇论文 arXiv ID") String arxivId1,
            @JsonProperty("arxiv_id2") @JsonPropertyDescription("第二篇论文 arXiv ID") String arxivId2,
            @JsonProperty("lang") @JsonPropertyDescription("语言: zh 或 en") String lang
    ) {}

    public record RecommendSimilarInput(
            @JsonProperty("arxiv_id") @JsonPropertyDescription("参考论文 arXiv ID") String arxivId,
            @JsonProperty("top_k") @JsonPropertyDescription("返回相似论文数量") int topK
    ) {}

    public record GenerateSurveyInput(
            @JsonProperty("topic") @JsonPropertyDescription("综述主题") String topic,
            @JsonProperty("mode") @JsonPropertyDescription("模式: survey(生成综述) 或 export(导出论文列表)") String mode,
            @JsonProperty("top_k") @JsonPropertyDescription("检索论文数量") int topK,
            @JsonProperty("lang") @JsonPropertyDescription("语言: zh 或 en") String lang,
            @JsonProperty("fmt") @JsonPropertyDescription("导出格式: json 或 text") String fmt
    ) {}

    // ──────────────────────────────────────────────
    //  Tool 1: search
    // ──────────────────────────────────────────────

    /**
     * Searches papers by keyword in multiple modes.
     *
     * @param query    search keyword
     * @param mode     "fts" (full-text), "semantic" (vector), or "list" (all papers)
     * @param topK     max results (clamped 1-50)
     * @param author   optional author filter
     * @param yearFrom optional year-from filter
     * @param yearTo   optional year-to filter
     * @return formatted search results
     */
    public String search(String query, String mode, int topK,
                         String author, String yearFrom, String yearTo) {
        try {
            int k = Math.clamp(topK <= 0 ? 10 : topK, 1, 50);
            String m = (mode == null || mode.isBlank()) ? "fts" : mode.trim().toLowerCase();
            String ownerId = ""; // default owner for agent tools

            return switch (m) {
                case "fts" -> {
                    List<Paper> papers = paperRepository.search(
                            query, null, author,
                            blankToNull(yearFrom), blankToNull(yearTo),
                            null, null, ownerId, k);
                    yield formatPaperList(papers, "全文搜索 \"" + query + "\"");
                }
                case "semantic" -> {
                    Map<String, Object> result = ragService.retrieve(query, k, ownerId);
                    @SuppressWarnings("unchecked")
                    List<Map<String, Object>> hits = (List<Map<String, Object>>) result.get("hits");
                    yield formatHitList(hits, "语义搜索 \"" + query + "\"");
                }
                case "list" -> {
                    List<Paper> papers = paperRepository.findAllByOwnerId(ownerId,
                            PageRequest.of(0, k));
                    yield formatPaperList(papers, "全部论文（最近 " + k + " 篇）");
                }
                default -> "未知搜索模式: " + m + "。支持的模式: fts, semantic, list";
            };
        } catch (Exception e) {
            log.error("search tool failed: {}", e.getMessage(), e);
            return "搜索失败: " + e.getMessage();
        }
    }

    // ──────────────────────────────────────────────
    //  Tool 2: getPaper
    // ──────────────────────────────────────────────

    /**
     * Retrieves full metadata for a single paper by arXiv ID.
     */
    public String getPaper(String arxivId) {
        try {
            if (arxivId == null || arxivId.isBlank()) {
                return "请提供有效的 arXiv ID";
            }
            Optional<Paper> paperOpt = paperRepository.findByArxivIdAndOwnerId(arxivId.trim(), "");
            if (paperOpt.isEmpty()) {
                return "未找到论文: " + arxivId + "（可能未入库或 arXiv ID 有误）";
            }
            return formatSinglePaper(paperOpt.get());
        } catch (Exception e) {
            log.error("getPaper tool failed: {}", e.getMessage(), e);
            return "获取论文失败: " + e.getMessage();
        }
    }

    // ──────────────────────────────────────────────
    //  Tool 3: summarizePaper
    // ──────────────────────────────────────────────

    /**
     * Generates a structured three-part summary for a paper.
     */
    public String summarizePaper(String arxivId, String lang) {
        try {
            if (arxivId == null || arxivId.isBlank()) {
                return "请提供有效的 arXiv ID";
            }
            String resolvedLang = (lang == null || lang.isBlank()) ? "zh" : lang.trim().toLowerCase();
            return ragService.summarizePaper(arxivId.trim(), resolvedLang);
        } catch (Exception e) {
            log.error("summarizePaper tool failed: {}", e.getMessage(), e);
            return "摘要生成失败: " + e.getMessage();
        }
    }

    // ──────────────────────────────────────────────
    //  Tool 4: getCitations
    // ──────────────────────────────────────────────

    /**
     * Retrieves the citation graph for a paper (outbound cites + inbound cited-by).
     */
    public String getCitations(String arxivId) {
        try {
            if (arxivId == null || arxivId.isBlank()) {
                return "请提供有效的 arXiv ID";
            }
            Map<String, Object> graph = citationService.getGraph(arxivId.trim());
            return formatCitationGraph(graph);
        } catch (Exception e) {
            log.error("getCitations tool failed: {}", e.getMessage(), e);
            return "获取引用关系失败: " + e.getMessage();
        }
    }

    // ──────────────────────────────────────────────
    //  Tool 5: comparePapers
    // ──────────────────────────────────────────────

    /**
     * Compares two papers side by side using the LLM.
     */
    public String comparePapers(String arxivId1, String arxivId2, String lang) {
        try {
            if (arxivId1 == null || arxivId1.isBlank() || arxivId2 == null || arxivId2.isBlank()) {
                return "请提供两篇论文的 arXiv ID";
            }
            String resolvedLang = (lang == null || lang.isBlank()) ? "zh" : lang.trim().toLowerCase();

            String text1 = readPaperText(arxivId1.trim());
            String text2 = readPaperText(arxivId2.trim());

            if (text1.isEmpty() && text2.isEmpty()) {
                return "两篇论文均无可用文本（可能未入库）";
            }
            if (text1.isEmpty()) {
                return "论文 " + arxivId1 + " 无可用文本（可能未入库）";
            }
            if (text2.isEmpty()) {
                return "论文 " + arxivId2 + " 无可用文本（可能未入库）";
            }

            String template = "zh".equals(resolvedLang)
                    ? PromptTemplates.COMPARE_PROMPT_ZH
                    : PromptTemplates.COMPARE_PROMPT_EN;
            String userPrompt = template
                    .replace("{text1}", text1)
                    .replace("{text2}", text2);

            List<Map<String, String>> messages = ChatClientService.messages(null, userPrompt);
            String result = chatClientService.chat(messages, config.effectiveLlmAgentModel(),
                    config.agentTemperature());
            return result != null ? result : "对比分析生成失败：模型返回为空";
        } catch (Exception e) {
            log.error("comparePapers tool failed: {}", e.getMessage(), e);
            return "论文对比失败: " + e.getMessage();
        }
    }

    // ──────────────────────────────────────────────
    //  Tool 6: recommendSimilar
    // ──────────────────────────────────────────────

    /**
     * Recommends similar papers based on pgvector embedding cosine distance.
     */
    public String recommendSimilar(String arxivId, int topK) {
        try {
            if (arxivId == null || arxivId.isBlank()) {
                return "请提供有效的 arXiv ID";
            }
            String id = arxivId.trim();
            int k = Math.clamp(topK <= 0 ? 5 : topK, 1, 20);

            // Get the source paper's embedding
            Optional<Paper> sourceOpt = paperRepository.findByArxivIdAndOwnerId(id, "");
            if (sourceOpt.isEmpty()) {
                return "未找到论文: " + id + "（可能未入库）";
            }
            Paper source = sourceOpt.get();
            if (source.getEmbedding() == null || source.getEmbedding().length == 0) {
                return "论文 " + id + " 尚未生成向量嵌入，请先入库（ingest）";
            }

            // Query similar papers by embedding (exclude the source paper itself by fetching k+1)
            String embeddingStr = Arrays.toString(source.getEmbedding());
            List<Paper> similar = paperRepository.findSimilarByEmbedding(embeddingStr, "", k + 1);

            // Filter out the source paper
            List<Paper> filtered = similar.stream()
                    .filter(p -> !id.equals(p.getArxivId()))
                    .limit(k)
                    .toList();

            if (filtered.isEmpty()) {
                return "未找到与 " + id + " 相似的论文";
            }

            StringBuilder sb = new StringBuilder();
            sb.append("与 ").append(id).append(" 相似的论文（Top ").append(filtered.size()).append("）：\n\n");
            for (int i = 0; i < filtered.size(); i++) {
                Paper p = filtered.get(i);
                sb.append("[").append(i + 1).append("] ");
                sb.append(nullToEmpty(p.getTitle())).append("\n");
                sb.append("    arXiv: ").append(p.getArxivId()).append("\n");
                if (StringUtils.hasText(p.getAuthors())) {
                    sb.append("    作者: ").append(p.getAuthors()).append("\n");
                }
                if (StringUtils.hasText(p.getAbstractText())) {
                    String abs = p.getAbstractText();
                    if (abs.length() > 300) {
                        abs = abs.substring(0, 300) + "…";
                    }
                    sb.append("    摘要: ").append(abs).append("\n");
                }
                sb.append("\n");
            }
            return sb.toString().trim();
        } catch (Exception e) {
            log.error("recommendSimilar tool failed: {}", e.getMessage(), e);
            return "相似论文推荐失败: " + e.getMessage();
        }
    }

    // ──────────────────────────────────────────────
    //  Tool 7: generateSurvey
    // ──────────────────────────────────────────────

    /**
     * Generates a multi-paper survey or exports paper data.
     */
    public String generateSurvey(String topic, String mode, int topK,
                                  String lang, String fmt) {
        try {
            if (topic == null || topic.isBlank()) {
                return "请提供综述主题";
            }
            int k = Math.clamp(topK <= 0 ? 10 : topK, 1, 50);
            String m = (mode == null || mode.isBlank()) ? "survey" : mode.trim().toLowerCase();
            String resolvedLang = (lang == null || lang.isBlank()) ? "zh" : lang.trim().toLowerCase();
            String resolvedFmt = (fmt == null || fmt.isBlank()) ? "text" : fmt.trim().toLowerCase();
            String ownerId = "";

            return switch (m) {
                case "survey" -> {
                    String surveyText = ragService.survey(topic, k, resolvedLang, ownerId);
                    yield surveyText != null ? surveyText : "综述生成失败";
                }
                case "export" -> {
                    Map<String, Object> result = ragService.retrieve(topic, k, ownerId);
                    @SuppressWarnings("unchecked")
                    List<Map<String, Object>> hits = (List<Map<String, Object>>) result.get("hits");
                    if (hits == null || hits.isEmpty()) {
                        yield "未找到与 \"" + topic + "\" 相关的论文";
                    }
                    if ("json".equals(resolvedFmt)) {
                        yield formatHitsAsJson(hits);
                    } else {
                        yield formatHitList(hits, "导出: \"" + topic + "\"");
                    }
                }
                default -> "未知导出模式: " + m + "。支持的模式: survey, export";
            };
        } catch (Exception e) {
            log.error("generateSurvey tool failed: {}", e.getMessage(), e);
            return "综述生成失败: " + e.getMessage();
        }
    }

    // ──────────────────────────────────────────────
    //  Formatting helpers
    // ──────────────────────────────────────────────

    private String formatPaperList(List<Paper> papers, String heading) {
        if (papers == null || papers.isEmpty()) {
            return heading + "：无结果";
        }
        StringBuilder sb = new StringBuilder();
        sb.append(heading).append("（共 ").append(papers.size()).append(" 篇）：\n\n");
        for (int i = 0; i < papers.size(); i++) {
            Paper p = papers.get(i);
            sb.append("[").append(i + 1).append("] ");
            sb.append(nullToEmpty(p.getTitle())).append("\n");
            sb.append("    arXiv: ").append(nullToEmpty(p.getArxivId())).append("\n");
            if (StringUtils.hasText(p.getAuthors())) {
                sb.append("    作者: ").append(p.getAuthors()).append("\n");
            }
            if (StringUtils.hasText(p.getPublished())) {
                sb.append("    发表: ").append(p.getPublished()).append("\n");
            }
            if (StringUtils.hasText(p.getAbstractText())) {
                String abs = p.getAbstractText();
                if (abs.length() > 200) {
                    abs = abs.substring(0, 200) + "…";
                }
                sb.append("    摘要: ").append(abs).append("\n");
            }
            if (StringUtils.hasText(p.getSource())) {
                sb.append("    来源: ").append(p.getSource()).append("\n");
            }
            sb.append("\n");
        }
        return sb.toString().trim();
    }

    private String formatHitList(List<Map<String, Object>> hits, String heading) {
        if (hits == null || hits.isEmpty()) {
            return heading + "：无结果";
        }
        StringBuilder sb = new StringBuilder();
        sb.append(heading).append("（共 ").append(hits.size()).append(" 条）：\n\n");
        for (int i = 0; i < hits.size(); i++) {
            Map<String, Object> hit = hits.get(i);
            sb.append("[").append(i + 1).append("] ");
            @SuppressWarnings("unchecked")
            Map<String, Object> meta = (Map<String, Object>) hit.get("metadata");
            if (meta != null) {
                sb.append(nullToEmpty(meta.get("title"))).append("\n");
                sb.append("    arXiv: ").append(nullToEmpty(hit.get("id"))).append("\n");
            } else {
                sb.append(nullToEmpty(hit.get("id"))).append("\n");
            }
            String doc = nullToEmpty(hit.get("document"));
            if (!doc.isEmpty()) {
                if (doc.length() > 300) {
                    doc = doc.substring(0, 300) + "…";
                }
                sb.append("    内容: ").append(doc).append("\n");
            }
            sb.append("\n");
        }
        return sb.toString().trim();
    }

    private String formatSinglePaper(Paper p) {
        StringBuilder sb = new StringBuilder();
        sb.append("论文详情：\n\n");
        sb.append("arXiv ID: ").append(nullToEmpty(p.getArxivId())).append("\n");
        sb.append("标题: ").append(nullToEmpty(p.getTitle())).append("\n");
        if (StringUtils.hasText(p.getAuthors())) {
            sb.append("作者: ").append(p.getAuthors()).append("\n");
        }
        if (StringUtils.hasText(p.getAbstractText())) {
            sb.append("摘要: ").append(p.getAbstractText()).append("\n");
        }
        if (StringUtils.hasText(p.getPublished())) {
            sb.append("发表日期: ").append(p.getPublished()).append("\n");
        }
        if (StringUtils.hasText(p.getPdfUrl())) {
            sb.append("PDF: ").append(p.getPdfUrl()).append("\n");
        }
        if (StringUtils.hasText(p.getSource())) {
            sb.append("来源: ").append(p.getSource()).append("\n");
        }
        sb.append("入库状态: ").append(nullToEmpty(p.getIngestStatus())).append("\n");
        return sb.toString().trim();
    }

    private String formatCitationGraph(Map<String, Object> graph) {
        StringBuilder sb = new StringBuilder();
        sb.append("引用关系图：\n\n");
        sb.append("论文: ").append(graph.get("arxiv_id")).append("\n\n");

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> cites = (List<Map<String, Object>>) graph.get("cites");
        sb.append("该论文引用了以下 ").append(cites != null ? cites.size() : 0).append(" 篇论文：\n");
        if (cites != null && !cites.isEmpty()) {
            for (int i = 0; i < cites.size(); i++) {
                Map<String, Object> c = cites.get(i);
                sb.append("  [").append(i + 1).append("] ");
                sb.append(nullToEmpty(c.get("cited_arxiv_id")));
                String title = nullToEmpty(c.get("cited_title"));
                if (!title.isEmpty()) {
                    sb.append(" — ").append(title);
                }
                sb.append("\n");
            }
        }

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> citedBy = (List<Map<String, Object>>) graph.get("cited_by");
        sb.append("\n被以下 ").append(citedBy != null ? citedBy.size() : 0).append(" 篇论文引用：\n");
        if (citedBy != null && !citedBy.isEmpty()) {
            for (int i = 0; i < citedBy.size(); i++) {
                Map<String, Object> c = citedBy.get(i);
                sb.append("  [").append(i + 1).append("] ");
                sb.append(nullToEmpty(c.get("citing_arxiv_id")));
                String title = nullToEmpty(c.get("citing_title"));
                if (!title.isEmpty()) {
                    sb.append(" — ").append(title);
                }
                sb.append("\n");
            }
        }

        return sb.toString().trim();
    }

    private String formatHitsAsJson(List<Map<String, Object>> hits) {
        try {
            return objectMapper.writerWithDefaultPrettyPrinter().writeValueAsString(hits);
        } catch (Exception e) {
            return "JSON 序列化失败: " + e.getMessage();
        }
    }

    /**
     * Reads a paper's text from the parsed JSON file, falling back to the database abstract.
     * Returns at most {@value #MAX_TEXT_CHARS} characters.
     */
    private String readPaperText(String arxivId) {
        // Try parsed JSON first
        Path jsonPath = Path.of(config.parsedDir(), arxivId + ".json");
        if (Files.isRegularFile(jsonPath)) {
            try {
                JsonNode root = objectMapper.readTree(jsonPath.toFile());
                StringBuilder sb = new StringBuilder();
                JsonNode sections = root.get("sections");
                if (sections != null && sections.isArray()) {
                    for (JsonNode sec : sections) {
                        appendSectionText(sb, sec);
                    }
                }
                String text = sb.toString().trim();
                if (!text.isEmpty()) {
                    if (text.length() > MAX_TEXT_CHARS) {
                        text = text.substring(0, MAX_TEXT_CHARS) + "…";
                    }
                    return text;
                }
            } catch (IOException e) {
                log.warn("Failed to read parsed JSON for {}: {}", arxivId, e.getMessage());
            }
        }

        // Fallback: database abstract
        Optional<Paper> paperOpt = paperRepository.findByArxivIdAndOwnerId(arxivId, "");
        if (paperOpt.isPresent() && StringUtils.hasText(paperOpt.get().getAbstractText())) {
            String abs = paperOpt.get().getAbstractText();
            if (abs.length() > MAX_TEXT_CHARS) {
                abs = abs.substring(0, MAX_TEXT_CHARS) + "…";
            }
            return abs;
        }
        return "";
    }

    private static void appendSectionText(StringBuilder sb, JsonNode section) {
        String content = jsonString(section, "content").strip();
        if (!content.isEmpty()) {
            if (!sb.isEmpty()) {
                sb.append("\n\n");
            }
            sb.append(content);
        }
        JsonNode subs = section.get("subsections");
        if (subs != null && subs.isArray()) {
            for (JsonNode sub : subs) {
                String subContent = jsonString(sub, "content").strip();
                if (!subContent.isEmpty()) {
                    if (!sb.isEmpty()) {
                        sb.append("\n\n");
                    }
                    sb.append(subContent);
                }
            }
        }
    }

    // ──────────────────────────────────────────────
    //  Static utilities
    // ──────────────────────────────────────────────

    private static String nullToEmpty(Object value) {
        return value == null ? "" : value.toString();
    }

    private static String blankToNull(String value) {
        return (value == null || value.isBlank()) ? null : value.trim();
    }

    private static String jsonString(JsonNode node, String field) {
        if (node == null) {
            return "";
        }
        JsonNode value = node.get(field);
        if (value == null || value.isNull()) {
            return "";
        }
        return value.asText();
    }
}
