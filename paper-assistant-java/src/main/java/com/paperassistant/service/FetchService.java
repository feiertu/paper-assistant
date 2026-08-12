package com.paperassistant.service;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.dataformat.xml.XmlMapper;
import com.fasterxml.jackson.dataformat.xml.annotation.JacksonXmlElementWrapper;
import com.fasterxml.jackson.dataformat.xml.annotation.JacksonXmlProperty;
import com.fasterxml.jackson.dataformat.xml.annotation.JacksonXmlRootElement;
import com.paperassistant.config.AppConfig;
import com.paperassistant.entity.Paper;
import com.paperassistant.repository.PaperRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.io.buffer.DataBuffer;
import org.springframework.core.io.buffer.DataBufferUtils;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.client.reactive.ReactorClientHttpConnector;
import org.springframework.stereotype.Service;
import org.springframework.web.reactive.function.client.ClientResponse;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientRequestException;
import org.springframework.web.reactive.function.client.WebClientResponseException;
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;
import reactor.netty.http.client.HttpClient;

import java.io.IOException;
import java.io.OutputStream;
import java.io.UncheckedIOException;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.OpenOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.time.Duration;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.concurrent.ThreadLocalRandom;
import java.util.concurrent.atomic.AtomicReference;

/**
 * 论文抓取服务 — Python {@code src/fetch/arxiv.py} 与 {@code src/fetch/download_pdf.py} 的 Java 移植。
 *
 * <p>职责与 Python 函数一一对应：
 * <ul>
 *   <li>{@link #fetchArxivMetadata(String, int)} — {@code fetch_arxiv_metadata()}：
 *       GET {@code export.arxiv.org/api/query}，3 次指数退避 + 抖动重试，Jackson XML 解析
 *       Atom feed，提取 id/title/summary/authors/published/pdf_url/categories；</li>
 *   <li>{@link #saveMetadataToDb(List, String)} — {@code save_metadata_to_db()}：
 *       去重（同 owner 已存在则跳过，不失败）后写入 {@code papers} 表，
 *       {@code source} 设为 {@code "arxiv:{primary_category}"}；</li>
 *   <li>{@link #fetchAndPersist(String, int, String)} — {@code fetch_and_persist()}：
 *       先按 {@link PaperRepository#findExistingIds(String)}（ingested）过滤，只保存新论文，
 *       返回 {@link FetchResult}；</li>
 *   <li>{@link #downloadPdf(String)} / {@link #downloadPdf(String, String)} —
 *       {@code download_with_resume()}：3 秒 arXiv 礼仪延迟 + HEAD Content-Length 判重 +
 *       HTTP Range 断点续传 + 外层指数退避重试。</li>
 * </ul>
 *
 * <p>方法签名均为同步（内部 {@code .block()}），与 Python 移植风格一致，便于控制器直接调用。
 */
@Service
public class FetchService {

    private static final Logger log = LoggerFactory.getLogger(FetchService.class);

    /** arXiv Atom API 端点（Python: {@code http://export.arxiv.org/api/query}）。 */
    static final String ARXIV_API_BASE = "http://export.arxiv.org/api/query";
    /** 标准 arXiv PDF 前缀（Python 兜底 URL + {@code download_pdf} 默认 URL）。 */
    static final String ARXIV_PDF_BASE = "https://arxiv.org/pdf/";
    /** 请求 User-Agent，arXiv 建议注明用途。 */
    private static final String USER_AGENT = "paper-assistant/0.1 (Java; +https://arxiv.org/api)";
    /** 总尝试次数（1 次初始 + 2 次重试，Python {@code max_retries=3}）。 */
    private static final int MAX_ATTEMPTS = 3;

    private final WebClient webClient;
    private final PaperRepository paperRepository;
    private final AppConfig config;

    /**
     * @param webClientBuilder Spring 注入的 {@code WebClient.Builder}（prototype 作用域），
     *                         按 {@code config.arxivRequestTimeout()} 配置响应超时。
     */
    public FetchService(WebClient.Builder webClientBuilder, PaperRepository paperRepository, AppConfig config) {
        this.paperRepository = paperRepository;
        this.config = config;
        int timeoutSec = config.arxivRequestTimeout() != null ? config.arxivRequestTimeout() : 60;
        this.webClient = webClientBuilder
                .defaultHeader(HttpHeaders.USER_AGENT, USER_AGENT)
                .clientConnector(new ReactorClientHttpConnector(HttpClient.create()
                        .followRedirect(true)
                        .responseTimeout(Duration.ofSeconds(timeoutSec))))
                .build();
    }

    // ---------------------------------------------------------------------
    // 1. fetchArxivMetadata — arXiv API 抓取（重试 + 解析）
    // ---------------------------------------------------------------------

    /**
     * 抓取 arXiv 论文元数据。内置重试（指数退避 + 抖动），与 Python
     * {@code fetch_arxiv_metadata()} 行为一致：连接错误和非 2xx 状态码都会退避重试，
     * 其它异常记录后中止。
     *
     * @param query      arXiv 查询串（null/blank 时用 {@code config.arxivQuery()}）
     * @param maxResults 最大结果数（{@code <=0} 时用 {@code config.arxivMaxResults()}）
     * @return 论文元数据字典列表（键与 Python 一致：id/title/authors/summary/published/pdf_url/
     *         categories/primary_category）；失败返回空列表
     */
    public List<Map<String, Object>> fetchArxivMetadata(String query, int maxResults) {
        String q = (query == null || query.isBlank()) ? config.arxivQuery() : query;
        int n = maxResults > 0 ? maxResults
                : (config.arxivMaxResults() != null ? config.arxivMaxResults() : 5);
        String url = ARXIV_API_BASE + "?search_query=" + urlEncode(q)
                + "&start=0&max_results=" + n
                + "&sortBy=submittedDate&sortOrder=descending";

        log.info("[FetchService] arXiv fetch: query={} max={}", q, n);

        for (int attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
            try {
                String xml = webClient.get().uri(url)
                        .retrieve()
                        .bodyToMono(String.class)
                        .block();
                List<Map<String, Object>> papers = parseArxivXml(xml);
                log.info("[FetchService] arXiv fetch: 获取 {} 篇论文", papers.size());
                return papers;
            } catch (WebClientResponseException e) {
                // 非 2xx 状态码 → 退避重试（Python: status != 200 → sleep(2**attempt)）
                log.error("[FetchService] arXiv API 返回 {} (attempt {}/{})",
                        e.getStatusCode().value(), attempt, MAX_ATTEMPTS);
                if (attempt < MAX_ATTEMPTS) {
                    sleep(backoffMillis(attempt));
                    continue;
                }
                return List.of();
            } catch (WebClientRequestException e) {
                // 连接错误：WebClient 把底层 IOException（connect/read timeout、reset 等）
                // 包装为 WebClientRequestException → 退避重试
                log.warn("[FetchService] arXiv 连接失败 (attempt {}/{})", attempt, MAX_ATTEMPTS);
                if (attempt < MAX_ATTEMPTS) {
                    sleep(backoffMillis(attempt));
                    continue;
                }
                log.error("[FetchService] arXiv fetch: {} 次重试均失败", MAX_ATTEMPTS, e);
                return List.of();
            } catch (Exception e) {
                // 其它异常 → 记录并中止（Python: RequestException → break）
                log.error("[FetchService] arXiv 请求异常: {}", e.getMessage(), e);
                return List.of();
            }
        }
        return List.of();
    }

    /**
     * 用 Jackson XML 解析 arXiv Atom feed → Python 字典结构的 List。
     *
     * <p>{@code public static} 便于单元测试（无需实例）。元素按 local name 匹配，
     * 忽略命名空间（Jackson XML 默认行为）。解析失败返回空列表而非抛异常。
     */
    public static List<Map<String, Object>> parseArxivXml(String xml) {
        if (xml == null || xml.isBlank()) {
            return List.of();
        }
        try {
            AtomFeed feed = XML_MAPPER.readValue(xml, AtomFeed.class);
            if (feed == null || feed.entry == null) {
                return List.of();
            }
            List<Map<String, Object>> papers = new ArrayList<>();
            for (AtomEntry entry : feed.entry) {
                if (entry == null || entry.id == null || entry.id.isBlank()) {
                    continue;
                }
                papers.add(entry.toMap());
            }
            return papers;
        } catch (Exception e) {
            log.error("[FetchService] 解析 arXiv Atom XML 失败: {}", e.getMessage(), e);
            return List.of();
        }
    }

    // ---------------------------------------------------------------------
    // 2. saveMetadataToDb — 写入 Paper 表
    // ---------------------------------------------------------------------

    /**
     * 将解析出的论文元数据写入 {@code papers} 表（Python {@code save_metadata_to_db()}）。
     *
     * <p>同 owner 已存在该 {@code arxiv_id} 时跳过并记 warning，不视为失败；
     * 数据库层的全局 UNIQUE(arxiv_id) 冲突也会被捕获（跨 owner 重复）后继续。
     *
     * @return 实际保存的论文数量
     */
    public int saveMetadataToDb(List<Map<String, Object>> papers, String ownerId) {
        int saved = 0;
        for (Map<String, Object> p : papers) {
            try {
                String arxivId = str(p.get("id"));
                if (arxivId.isEmpty()) {
                    continue;
                }
                Optional<Paper> existing = paperRepository.findByArxivIdAndOwnerId(arxivId, ownerId);
                if (existing.isPresent()) {
                    log.warn("[FetchService] 跳过已入库论文: {}", arxivId);
                    continue;
                }
                String cat = str(p.get("primary_category"));
                String source = cat.isEmpty() ? "arxiv" : "arxiv:" + cat;
                Paper paper = Paper.builder()
                        .arxivId(arxivId)
                        .title(str(p.get("title")))
                        .authors(str(p.get("authors")))
                        .abstractText(str(p.get("summary")))
                        .published(str(p.get("published")))
                        .pdfUrl(str(p.get("pdf_url")))
                        .source(source)
                        .ingestStatus("pending")
                        .chunkCount(0)
                        .ownerId(ownerId)
                        .build();
                paperRepository.save(paper);
                saved++;
            } catch (Exception e) {
                log.warn("[FetchService] 保存元数据失败 {}: {}", p.get("id"), e.getMessage());
            }
        }
        return saved;
    }

    // ---------------------------------------------------------------------
    // 3. fetchAndPersist — 抓取 + 过滤 + 保存
    // ---------------------------------------------------------------------

    /**
     * 抓取 arXiv 元数据并保存到数据库（Python {@code fetch_and_persist()}）。
     * 已入库（ingested）的论文自动跳过不重复抓取。
     */
    public FetchResult fetchAndPersist(String query, int maxResults, String ownerId) {
        List<Map<String, Object>> papers = fetchArxivMetadata(query, maxResults);

        Set<String> existingIds = new HashSet<>(paperRepository.findExistingIds(ownerId));
        FetchPartition partition = partitionPapers(papers, existingIds);

        if (!partition.newPapers().isEmpty()) {
            int saved = saveMetadataToDb(partition.newPapers(), ownerId);
            if (!partition.skippedPapers().isEmpty()) {
                log.info("[FetchService] 已保存 {}/{} 条元数据，跳过 {} 篇已入库论文",
                        saved, partition.newPapers().size(), partition.skippedPapers().size());
            } else {
                log.info("[FetchService] 已保存 {}/{} 条元数据到数据库", saved, papers.size());
            }
        } else if (!papers.isEmpty() && partition.skippedPapers().size() == papers.size()) {
            log.info("[FetchService] 全部 {} 篇论文已入库，跳过", papers.size());
        }

        List<Map<String, Object>> resultPapers = partition.newPapers().isEmpty() ? papers : partition.newPapers();
        return new FetchResult(papers.size(), partition.newPapers().size(), partition.skippedPapers(), resultPapers);
    }

    /**
     * 按已入库 id 集合把论文分为「新论文」与「跳过论文」。
     * package-private 以便单元测试（Python 内联过滤逻辑）。
     */
    static FetchPartition partitionPapers(List<Map<String, Object>> papers, Set<String> existingIds) {
        List<Map<String, Object>> newPapers = new ArrayList<>();
        List<Map<String, Object>> skipped = new ArrayList<>();
        for (Map<String, Object> p : papers) {
            String id = str(p.get("id"));
            if (existingIds.contains(id)) {
                Map<String, Object> s = new LinkedHashMap<>();
                s.put("id", id);
                s.put("title", p.get("title"));
                skipped.add(s);
            } else {
                newPapers.add(p);
            }
        }
        return new FetchPartition(newPapers, skipped);
    }

    /** 论文分区结果：新论文 + 跳过论文。 */
    record FetchPartition(List<Map<String, Object>> newPapers, List<Map<String, Object>> skippedPapers) {
    }

    // ---------------------------------------------------------------------
    // 4. downloadPdf — PDF 下载（3 秒延迟 + Range 断点续传 + 重试）
    // ---------------------------------------------------------------------

    /**
     * 按标准 arXiv URL 下载 PDF（Python {@code download_with_resume()}）。
     *
     * @throws IOException 目录创建失败，或重试耗尽后仍无法下载
     */
    public Path downloadPdf(String arxivId) throws IOException {
        return downloadPdf(arxivId, ARXIV_PDF_BASE + arxivId + ".pdf");
    }

    /**
     * 下载 {@code pdfUrl} 到 {@code config.rawPdfDir()/arxivId.pdf}。
     *
     * <p>下载前先延迟 {@code config.pdfDownloadDelay()} 秒（默认 3s）遵守 arXiv 礼仪；
     * HEAD 获取 Content-Length，本地已有完整文件则直接返回；否则 HTTP Range 断点续传，
     * 失败时指数退避重试（最多 {@link #MAX_ATTEMPTS} 次）。
     *
     * @throws IOException 目录创建失败，或重试耗尽后仍无法下载
     */
    public Path downloadPdf(String arxivId, String pdfUrl) throws IOException {
        double delay = config.pdfDownloadDelay() != null ? config.pdfDownloadDelay() : 3.0;
        if (delay > 0) {
            sleep((long) (delay * 1000));
        }

        Path dir = Path.of(config.rawPdfDir());
        Files.createDirectories(dir);
        Path target = dir.resolve(arxivId + ".pdf");

        long total = headContentLength(pdfUrl);
        if (Files.exists(target) && total >= 0 && Files.size(target) == total) {
            log.info("[FetchService] 已存在（完整）: {}", arxivId);
            return target;
        }
        long resumePos = initialResumePos(target, total);

        for (int attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
            try {
                streamDownload(pdfUrl, target, resumePos);
                log.info("[FetchService] 下载成功: {}", arxivId);
                return target;
            } catch (Exception e) {
                if (attempt < MAX_ATTEMPTS) {
                    long delayMillis = backoffMillis(attempt);
                    sleep(delayMillis);
                    try {
                        resumePos = Files.exists(target) ? Files.size(target) : 0;
                    } catch (IOException ignored) {
                        resumePos = 0;
                    }
                    log.warn("[FetchService] 下载第 {}/{} 次失败，{}s 后重试… ({})",
                            attempt, MAX_ATTEMPTS, delayMillis / 1000.0, e.getMessage());
                } else {
                    log.error("[FetchService] {}: {} 次重试均失败", arxivId, MAX_ATTEMPTS, e);
                    throw new IOException("PDF 下载失败（重试 " + MAX_ATTEMPTS + " 次）: " + arxivId, e);
                }
            }
        }
        return target; // unreachable
    }

    // ---------------------------------------------------------------------
    // 下载内部辅助
    // ---------------------------------------------------------------------

    /** HEAD 请求获取 Content-Length；失败或非 2xx 返回 -1。 */
    private long headContentLength(String pdfUrl) {
        try {
            return webClient.head().uri(pdfUrl)
                    .exchangeToMono(response -> {
                        if (!response.statusCode().is2xxSuccessful()) {
                            return response.releaseBody().then(Mono.just(-1L));
                        }
                        String cl = response.headers().header(HttpHeaders.CONTENT_LENGTH).stream()
                                .findFirst().orElse(null);
                        return response.releaseBody().then(Mono.just(cl == null ? -1L : Long.parseLong(cl.trim())));
                    })
                    .block();
        } catch (Exception e) {
            return -1;
        }
    }

    /**
     * 计算断点位置：已有文件时返回本地大小（续传）；本地比服务端还大 → 从头；
     * 无法获取 Content-Length → 删除已有文件重新下载（Python 保守策略）。
     */
    private long initialResumePos(Path target, long total) throws IOException {
        if (!Files.exists(target)) {
            return 0;
        }
        long local = Files.size(target);
        if (total >= 0) {
            return local > total ? 0 : local;
        }
        Files.deleteIfExists(target);
        return 0;
    }

    /**
     * 流式下载到 {@code target}，支持 HTTP Range 续传。
     * 服务器忽略 Range（返回 200 全文）时从头写；返回 206 且请求过 Range 时追加。
     */
    private void streamDownload(String pdfUrl, Path target, long resumePos) throws IOException {
        boolean resuming = resumePos > 0;
        HttpHeaders headers = new HttpHeaders();
        if (resuming) {
            headers.set(HttpHeaders.RANGE, "bytes=" + resumePos + "-");
        }
        AtomicReference<OutputStream> outRef = new AtomicReference<>();
        try {
            webClient.get().uri(pdfUrl)
                    .headers(h -> h.addAll(headers))
                    .exchangeToMono(response -> {
                        int code = response.statusCode().value();
                        if (code != HttpStatus.OK.value() && code != HttpStatus.PARTIAL_CONTENT.value()) {
                            return response.createException().flatMap(Mono::error);
                        }
                        boolean append = resuming && code == HttpStatus.PARTIAL_CONTENT.value();
                        OpenOption[] options = append
                                ? new OpenOption[]{StandardOpenOption.CREATE, StandardOpenOption.WRITE,
                                StandardOpenOption.APPEND}
                                : new OpenOption[]{StandardOpenOption.CREATE, StandardOpenOption.WRITE,
                                StandardOpenOption.TRUNCATE_EXISTING};
                        try {
                            OutputStream out = Files.newOutputStream(target, options);
                            outRef.set(out);
                            return writeBody(response, out);
                        } catch (IOException e) {
                            return Mono.error(e);
                        }
                    })
                    .block();
        } catch (UncheckedIOException e) {
            throw (IOException) e.getCause();
        } finally {
            OutputStream out = outRef.get();
            if (out != null) {
                try {
                    out.close();
                } catch (IOException ignored) {
                    // best-effort
                }
            }
        }
    }

    /** 把响应 body（DataBuffer 流）逐块写入 {@code out}，写失败以 UncheckedIOException 中止流。 */
    private Mono<Void> writeBody(ClientResponse response, OutputStream out) {
        return response.bodyToFlux(DataBuffer.class)
                .publishOn(Schedulers.boundedElastic())
                .doOnNext(buffer -> {
                    try {
                        byte[] bytes = new byte[buffer.readableByteCount()];
                        buffer.read(bytes);
                        out.write(bytes);
                    } catch (IOException e) {
                        throw new UncheckedIOException(e);
                    } finally {
                        DataBufferUtils.release(buffer);
                    }
                })
                .then();
    }

    // ---------------------------------------------------------------------
    // Atom feed DTO（Jackson XML，local-name 匹配，忽略命名空间）
    // ---------------------------------------------------------------------

    /**
     * 忽略未知字段/属性：arXiv Atom feed 的 {@code <link>} 常带 {@code rel} 等额外属性，
     * 与 Python ElementTree 一样只读所需字段，未知属性不报错。
     */
    private static final XmlMapper XML_MAPPER = createXmlMapper();

    private static XmlMapper createXmlMapper() {
        XmlMapper mapper = new XmlMapper();
        mapper.configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, false);
        return mapper;
    }

    /** {@code <feed>} 根元素。 */
    @JacksonXmlRootElement(localName = "feed")
    static class AtomFeed {
        @JacksonXmlProperty(localName = "entry")
        @JacksonXmlElementWrapper(useWrapping = false)
        public List<AtomEntry> entry;
    }

    /** {@code <entry>} 元素。 */
    static class AtomEntry {
        @JacksonXmlProperty(localName = "id")
        public String id;
        @JacksonXmlProperty(localName = "title")
        public String title;
        @JacksonXmlProperty(localName = "summary")
        public String summary;
        @JacksonXmlProperty(localName = "published")
        public String published;
        @JacksonXmlProperty(localName = "author")
        @JacksonXmlElementWrapper(useWrapping = false)
        public List<AtomAuthor> author;
        @JacksonXmlProperty(localName = "category")
        @JacksonXmlElementWrapper(useWrapping = false)
        public List<AtomCategory> category;
        @JacksonXmlProperty(localName = "link")
        @JacksonXmlElementWrapper(useWrapping = false)
        public List<AtomLink> link;

        /** 转换为 Python 契约字典。 */
        Map<String, Object> toMap() {
            String arxivId = lastSegment(id);
            String title = this.title == null ? "" : this.title.strip().replace("\n", " ");
            String summary = this.summary == null ? "" : this.summary.strip();

            List<String> names = new ArrayList<>();
            if (author != null) {
                for (AtomAuthor a : author) {
                    if (a != null && a.name != null && !a.name.isBlank()) {
                        names.add(a.name.strip());
                    }
                }
            }
            String authors = String.join(", ", names);
            String published = this.published == null ? "" : this.published.strip();

            List<String> categories = new ArrayList<>();
            if (category != null) {
                for (AtomCategory c : category) {
                    if (c != null && c.term != null && !c.term.isBlank()) {
                        categories.add(c.term);
                    }
                }
            }
            String primaryCat = categories.isEmpty() ? "" : categories.get(0);

            String pdfUrl = findPdfUrl();
            if (pdfUrl == null) {
                pdfUrl = ARXIV_PDF_BASE + arxivId + ".pdf";
            }

            Map<String, Object> paper = new LinkedHashMap<>();
            paper.put("id", arxivId);
            paper.put("title", title);
            paper.put("authors", authors);
            paper.put("summary", summary);
            paper.put("published", published);
            paper.put("pdf_url", pdfUrl);
            paper.put("categories", categories);
            paper.put("primary_category", primaryCat);
            return paper;
        }

        /** 从 link 中找 PDF 链接：type=application/pdf | href 以 .pdf 结尾 | title=pdf。 */
        private String findPdfUrl() {
            if (link == null) {
                return null;
            }
            for (AtomLink l : link) {
                if (l == null || l.href == null || l.href.isBlank()) {
                    continue;
                }
                if ("application/pdf".equals(l.type)
                        || l.href.endsWith(".pdf")
                        || "pdf".equals(l.title)) {
                    return l.href;
                }
            }
            return null;
        }
    }

    /** {@code <author>} 元素。 */
    static class AtomAuthor {
        @JacksonXmlProperty(localName = "name")
        public String name;
    }

    /** {@code <category>} 元素（term 属性）。 */
    static class AtomCategory {
        @JacksonXmlProperty(localName = "term", isAttribute = true)
        public String term;
    }

    /** {@code <link>} 元素（href/type/title 属性）。 */
    static class AtomLink {
        @JacksonXmlProperty(localName = "href", isAttribute = true)
        public String href;
        @JacksonXmlProperty(localName = "type", isAttribute = true)
        public String type;
        @JacksonXmlProperty(localName = "title", isAttribute = true)
        public String title;
    }

    // ---------------------------------------------------------------------
    // 工具方法
    // ---------------------------------------------------------------------

    /** 取 URL 最后一段作为 arxiv_id（Python: {@code id_url.split('/')[-1]}）。 */
    private static String lastSegment(String url) {
        if (url == null || url.isEmpty()) {
            return "";
        }
        int slash = url.lastIndexOf('/');
        return slash >= 0 && slash < url.length() - 1 ? url.substring(slash + 1) : url;
    }

    /**
     * 指数退避 + 抖动（毫秒）：wait = 2^(attempt-1) 秒 + [0,1) 秒随机。
     * 首次重试约 1s，累计等待 1s→3s→7s（与 Python {@code 2**attempt + 抖动} 同结构）。
     */
    private static long backoffMillis(int attempt) {
        long base = (long) Math.pow(2, attempt - 1) * 1000L;
        double jitter = ThreadLocalRandom.current().nextDouble();
        return base + (long) (jitter * 1000);
    }

    private static void sleep(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            log.warn("[FetchService] sleep 被打断", e);
        }
    }

    private static String urlEncode(String value) {
        return URLEncoder.encode(value, StandardCharsets.UTF_8);
    }

    private static String str(Object v) {
        return v == null ? "" : String.valueOf(v);
    }
}
