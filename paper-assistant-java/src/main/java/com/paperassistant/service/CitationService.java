package com.paperassistant.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.paperassistant.config.AppConfig;
import com.paperassistant.entity.Citation;
import com.paperassistant.entity.Paper;
import com.paperassistant.repository.CitationRepository;
import com.paperassistant.repository.PaperRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.TreeSet;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Stream;

/**
 * 引用关系服务 — Python {@code src/parse/citations.py}（提取）与 {@code CitationDAO}
 * （图查询/批量插入）的 Java 移植。
 *
 * <p>两个公开方法：
 * <ul>
 *   <li>{@link #getGraph(String)} — 从 {@code citations} 表查询出向（cites）与入向
 *       （cited_by）引用，返回 {@code {"arxiv_id", "cites":[...], "cited_by":[...]}}。
 *       条目字段与 Python {@code CitationDAO.find_citations_from/to()} 一致，含
 *       {@code in_db}（关联论文是否已入库，对应 Python 的 LEFT JOIN papers）。</li>
 *   <li>{@link #batchExtract(List)} — 遍历 {@code parsedDir} 下的 {@code *.json}，
 *       从 References/Bibliography 章节提取 arXiv ID，去重后写入 {@code citations} 表。
 *       返回 {@code {"processed": N, "citations": M}}（对应 Python
 *       {@code batch_extract_citations()}）。</li>
 * </ul>
 */
@Service
public class CitationService {

    private static final Logger log = LoggerFactory.getLogger(CitationService.class);

    // ---------- 提取用正则（与 Python citations.py 逐一对齐） ----------

    /** 参考文献章节标题（小写），Python {@code _collect_reference_texts} 识别集合。 */
    private static final Set<String> REFERENCE_TITLES =
            Set.of("references", "bibliography", "reference");

    /** arXiv URL 模式：{@code arxiv.org/abs/XXXX.XXXXX} 或 {@code arxiv.org/pdf/...}。 */
    private static final Pattern ARXIV_URL_RE =
            Pattern.compile("arxiv\\.org/(?:abs|pdf)/(\\d{4}\\.\\d{4,5}(?:v\\d+)?)",
                    Pattern.CASE_INSENSITIVE);

    /** arXiv 前缀模式（要求显式 {@code :} 或 {@code #} 分隔符）。 */
    private static final Pattern ARXIV_PREFIX_RE =
            Pattern.compile("arxiv\\s*[:#]\\s*(\\d{4}\\.\\d{4,5}(?:v\\d+)?)",
                    Pattern.CASE_INSENSITIVE);

    /** 通用 arXiv ID 模式（Python {@code _ARXIV_ID_RE}，前缀可选）。 */
    private static final Pattern ARXIV_ID_RE =
            Pattern.compile("(?:arxiv\\s*[:#]?\\s*)?(\\d{4}\\.\\d{4,5}(?:v\\d+)?)",
                    Pattern.CASE_INSENSITIVE);

    /** 按文献编号切分：新行后跟 {@code [N]} 或 {@code N.}。 */
    private static final Pattern ENTRY_SPLIT_RE =
            Pattern.compile("\\n(?=\\s*\\[\\d+\\]|\\s*\\d+\\.\\s)");

    /** 去掉条目开头编号前缀（{@code [1]} / {@code 1.} / {@code 12.}）。 */
    private static final Pattern ENTRY_NUM_PREFIX_RE = Pattern.compile("^\\[?\\d+\\]?\\.?\\s*");

    /** 句子切分（Python {@code re.split(r'[.。!！?？]\s+')}）。 */
    private static final Pattern SENTENCE_SPLIT_RE = Pattern.compile("[.。!！?？]\\s+");

    /** 从作者-年份行提取标题（Python {@code _extract_title_from_entry}）。 */
    private static final Pattern AUTHOR_YEAR_RE =
            Pattern.compile("(?:\\)\\.|,?\\s*\\d{4}[a-z]?\\.?)\\s*(.+)");

    /** 引用上下文 / 标题最大长度（Python {@code entry[:300]} / {@code [:200]}）。 */
    private static final int MAX_CONTEXT_LEN = 300;
    private static final int MAX_TITLE_LEN = 200;

    // ---------- 依赖 ----------

    private final CitationRepository citationRepository;
    private final PaperRepository paperRepository;
    private final AppConfig appConfig;
    private final ObjectMapper objectMapper;

    public CitationService(CitationRepository citationRepository,
                           PaperRepository paperRepository,
                           AppConfig appConfig,
                           ObjectMapper objectMapper) {
        this.citationRepository = citationRepository;
        this.paperRepository = paperRepository;
        this.appConfig = appConfig;
        this.objectMapper = objectMapper;
    }

    // ---------------------------------------------------------------------
    // 公开 API
    // ---------------------------------------------------------------------

    /**
     * 获取论文引用关系图（Python {@code CitationDAO.get_graph()}）。
     *
     * @param arxivId 论文 arXiv ID
     * @return {@code {"arxiv_id", "cites":[{cited_arxiv_id, cited_title, context, in_db}],
     *         "cited_by":[{citing_arxiv_id, citing_title, context, in_db}]}}
     *         —— {@code cites} 为该论文引用了哪些论文（出向），{@code cited_by} 为哪些
     *         论文引用了它（入向）。条目按 id 升序（对应 Python {@code ORDER BY c.id}）。
     */
    public Map<String, Object> getGraph(String arxivId) {
        String id = arxivId == null ? "" : arxivId;

        List<Map<String, Object>> cites = new ArrayList<>();
        for (Citation c : sorted(citationRepository.findByCitingArxivId(id))) {
            String citedId = c.getCitedArxivId();
            Optional<Paper> paper = paperRepository.findByArxivId(citedId);
            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("cited_arxiv_id", citedId);
            entry.put("cited_title", hasText(c.getCitedTitle()) ? c.getCitedTitle() : paperTitle(paper));
            entry.put("context", str(c.getContext()));
            entry.put("in_db", paper.isPresent());
            cites.add(entry);
        }

        List<Map<String, Object>> citedBy = new ArrayList<>();
        for (Citation c : sorted(citationRepository.findByCitedArxivId(id))) {
            String citingId = c.getCitingArxivId();
            Optional<Paper> paper = paperRepository.findByArxivId(citingId);
            String title = paperTitle(paper);
            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("citing_arxiv_id", citingId);
            // Python: paper_title or citing_arxiv_id（未入库时回退为 ID 本身）
            entry.put("citing_title", title.isEmpty() ? citingId : title);
            entry.put("context", str(c.getContext()));
            entry.put("in_db", paper.isPresent());
            citedBy.add(entry);
        }

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("arxiv_id", id);
        result.put("cites", cites);
        result.put("cited_by", citedBy);
        return result;
    }

    /**
     * 批量提取引用关系（Python {@code batch_extract_citations()}）。
     *
     * <p>遍历 {@code parsedDir} 下所有 {@code *.json}（或仅处理 {@code arxivIds}
     * 指定的论文），从 References/Bibliography 章节提取 arXiv ID，排除自身引用后
     * 去重写入 {@code citations} 表。
     *
     * @param arxivIds 指定论文 ID 列表；{@code null} 或空则处理 parsed 目录全部 JSON
     * @return {@code {"processed": N, "citations": M}}；parsed 目录不存在时返回
     *         {@code {"processed": 0, "citations": 0, "error": "parsed 目录不存在"}}
     */
    public Map<String, Object> batchExtract(List<String> arxivIds) {
        Path parsedDir = Path.of(appConfig.parsedDir());
        if (!Files.isDirectory(parsedDir)) {
            log.warn("[CitationService] parsed 目录不存在: {}", parsedDir);
            return Map.of("processed", 0, "citations", 0, "error", "parsed 目录不存在");
        }

        List<String> ids = (arxivIds == null || arxivIds.isEmpty())
                ? listJsonStems(parsedDir)
                : new ArrayList<>(arxivIds);

        int total = 0;
        for (String aid : ids) {
            List<Reference> refs = extractReferencesFromParsed(aid);
            if (!refs.isEmpty()) {
                int inserted = batchInsert(aid, refs);
                total += inserted;
                log.info("[CitationService] 引用提取: {} → {} 条引用", aid, inserted);
            }
        }
        log.info("[CitationService] 批量引用提取完成: {} 篇论文, {} 条引用", ids.size(), total);

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("processed", ids.size());
        result.put("citations", total);
        return result;
    }

    // ---------------------------------------------------------------------
    // 提取逻辑（Python citations.py 逐行移植，静态方法便于单元测试）
    // ---------------------------------------------------------------------

    /**
     * 从一段文本提取 arXiv ID 列表（去重、排序）。
     *
     * <p>支持格式（Python {@code extract_arxiv_ids()}）：
     * {@code arXiv:2301.12345}、{@code arxiv.org/abs/2301.12345}、
     * {@code arxiv.org/pdf/2301.12345v1}、独立出现的 {@code 2301.12345}。
     */
    static List<String> extractArxivIds(String text) {
        Set<String> ids = new TreeSet<>();

        Matcher url = ARXIV_URL_RE.matcher(text);
        while (url.find()) {
            ids.add(url.group(1));
        }
        Matcher prefix = ARXIV_PREFIX_RE.matcher(text);
        while (prefix.find()) {
            ids.add(prefix.group(1));
        }
        Matcher generic = ARXIV_ID_RE.matcher(text);
        while (generic.find()) {
            String raw = generic.group(1);
            // 过滤误匹配：太短或纯数字（Python len >= 9 and "." in raw）
            if (raw.length() >= 9 && raw.contains(".")) {
                ids.add(raw);
            }
        }
        return new ArrayList<>(ids);
    }

    /** 从 parsed JSON 提取引用关系 {@code [(cited_id, title, context), ...]}。 */
    private List<Reference> extractReferencesFromParsed(String arxivId) {
        Path jsonPath = Path.of(appConfig.parsedDir(), arxivId + ".json");
        if (!Files.isRegularFile(jsonPath)) {
            log.debug("[CitationService] parsed JSON 不存在: {}", arxivId);
            return List.of();
        }

        JsonNode data;
        try {
            data = objectMapper.readTree(jsonPath.toFile());
        } catch (IOException e) {
            log.warn("[CitationService] 无法读取 parsed JSON {}: {}", arxivId, e.getMessage());
            return List.of();
        }

        List<String> refTexts = collectReferenceTexts(data);
        if (refTexts.isEmpty()) {
            return List.of();
        }

        String fullRefText = String.join("\n", refTexts);
        List<String> entries = splitReferenceEntries(fullRefText);

        List<Reference> results = new ArrayList<>();
        for (String entry : entries) {
            for (String citedId : extractArxivIds(entry)) {
                // 排除自身引用：比较去版本号后的 base ID
                if (stripVersion(citedId).equals(stripVersion(arxivId))) {
                    continue;
                }
                String title = extractTitleFromEntry(entry);
                String context = entry.length() > MAX_CONTEXT_LEN
                        ? entry.substring(0, MAX_CONTEXT_LEN) : entry;
                results.add(new Reference(citedId, title, context));
            }
        }
        return results;
    }

    /** 从 parsed JSON 收集 References/Bibliography 相关章节文本。 */
    static List<String> collectReferenceTexts(JsonNode data) {
        List<String> texts = new ArrayList<>();
        JsonNode sections = data.get("sections");
        if (sections == null || !sections.isArray()) {
            return texts;
        }
        for (JsonNode sec : sections) {
            String title = jsonString(sec, "title").strip().toLowerCase(Locale.ROOT);
            if (REFERENCE_TITLES.contains(title)) {
                String content = jsonString(sec, "content").strip();
                if (!content.isEmpty()) {
                    texts.add(content);
                }
            }
            JsonNode subs = sec.get("subsections");
            if (subs != null && subs.isArray()) {
                for (JsonNode sub : subs) {
                    String stitle = jsonString(sub, "title").strip().toLowerCase(Locale.ROOT);
                    if (REFERENCE_TITLES.contains(stitle)) {
                        String content = jsonString(sub, "content").strip();
                        if (!content.isEmpty()) {
                            texts.add(content);
                        }
                    }
                }
            }
        }
        return texts;
    }

    /** 按文献编号（{@code [N]} / {@code N.}）切分引用条目；无编号时按双换行切分。 */
    static List<String> splitReferenceEntries(String refText) {
        List<String> rawParts = splitOnLookahead(refText);
        List<String> base = rawParts.size() <= 1
                ? List.of(refText.split("\\n\\n"))
                : rawParts;

        List<String> result = new ArrayList<>();
        for (String part : base) {
            String s = part.strip();
            if (!s.isEmpty() && s.length() > 20) {
                result.add(s);
            }
        }
        return result;
    }

    /** 从引用条目中启发式提取论文标题（Python {@code _extract_title_from_entry}）。 */
    static String extractTitleFromEntry(String entry) {
        String cleaned = ENTRY_NUM_PREFIX_RE.matcher(entry.strip()).replaceFirst("");
        String[] sentences = SENTENCE_SPLIT_RE.split(cleaned);
        String first = sentences.length > 0 ? sentences[0].strip() : truncate(cleaned, MAX_TITLE_LEN);
        Matcher m = AUTHOR_YEAR_RE.matcher(first);
        if (m.find()) {
            return truncate(m.group(1).strip(), MAX_TITLE_LEN);
        }
        return truncate(first, MAX_TITLE_LEN);
    }

    /** 去掉 arXiv ID 的版本后缀（Python {@code id.split("v")[0]}）。 */
    static String stripVersion(String id) {
        int v = id.indexOf('v');
        return v >= 0 ? id.substring(0, v) : id;
    }

    // ---------------------------------------------------------------------
    // 内部辅助
    // ---------------------------------------------------------------------

    /** 带 id 升序排序（对应 Python {@code ORDER BY c.id}）。 */
    private static List<Citation> sorted(List<Citation> list) {
        List<Citation> copy = new ArrayList<>(list);
        copy.sort(Comparator.comparing(Citation::getId));
        return copy;
    }

    /**
     * 批量插入引用关系，去重（Python {@code INSERT OR IGNORE} 语义：
     * citations 表 {@code UNIQUE(citing_arxiv_id, cited_arxiv_id)}）。
     */
    private int batchInsert(String citingArxivId, List<Reference> refs) {
        int count = 0;
        for (Reference ref : refs) {
            try {
                if (citationRepository.countByCitingArxivIdAndCitedArxivId(
                        citingArxivId, ref.citedArxivId()) > 0) {
                    continue;
                }
                citationRepository.save(Citation.builder()
                        .citingArxivId(citingArxivId)
                        .citedArxivId(ref.citedArxivId())
                        .citedTitle(ref.citedTitle())
                        .context(ref.context())
                        .build());
                count++;
            } catch (Exception e) {
                log.warn("[CitationService] 批量引用插入跳过: {} → {}: {}",
                        citingArxivId, ref.citedArxivId(), e.getMessage());
            }
        }
        return count;
    }

    /** 列出 parsed 目录下所有 {@code *.json} 的文件名（去掉扩展名），排序。 */
    private static List<String> listJsonStems(Path parsedDir) {
        try (Stream<Path> stream = Files.list(parsedDir)) {
            return stream
                    .filter(Files::isRegularFile)
                    .filter(p -> p.getFileName().toString().endsWith(".json"))
                    .map(p -> {
                        String name = p.getFileName().toString();
                        return name.substring(0, name.length() - ".json".length());
                    })
                    .sorted()
                    .toList();
        } catch (IOException e) {
            log.warn("[CitationService] 读取 parsed 目录失败: {}", e.getMessage());
            return List.of();
        }
    }

    /** Python {@code re.split}（保留所有段，含空段）的等价实现。 */
    private static List<String> splitOnLookahead(String text) {
        List<String> parts = new ArrayList<>();
        Matcher m = ENTRY_SPLIT_RE.matcher(text);
        int last = 0;
        while (m.find()) {
            parts.add(text.substring(last, m.start()));
            // 分隔符是 `\n`（被匹配消耗），下一段从 m.end() 开始（Python re.split 同语义）
            last = m.end();
        }
        parts.add(text.substring(last));
        return parts;
    }

    /** 论文表标题；未入库时返回空串。 */
    private static String paperTitle(Optional<Paper> paper) {
        if (paper.isEmpty()) {
            return "";
        }
        String title = paper.get().getTitle();
        return title == null ? "" : title;
    }

    /** 截断到 {@code maxLen}（Python {@code [:n]}）。 */
    private static String truncate(String s, int maxLen) {
        if (s == null) {
            return "";
        }
        return s.length() <= maxLen ? s : s.substring(0, maxLen);
    }

    private static boolean hasText(String s) {
        return s != null && !s.isBlank();
    }

    private static String str(Object v) {
        return v == null ? "" : String.valueOf(v);
    }

    /** 安全读取 JSON 节点字段文本，缺失/为 null 返回空串（与 RagService 一致）。 */
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

    /** 一条待插入的引用关系。 */
    record Reference(String citedArxivId, String citedTitle, String context) {
    }
}
