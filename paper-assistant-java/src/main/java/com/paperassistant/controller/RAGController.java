package com.paperassistant.controller;

import com.paperassistant.dto.request.IngestRequest;
import com.paperassistant.dto.request.IngestTextRequest;
import com.paperassistant.dto.request.RAGQueryRequest;
import com.paperassistant.dto.request.RetrieveRequest;
import com.paperassistant.dto.request.SummarizeRequest;
import com.paperassistant.dto.request.SurveyRequest;
import com.paperassistant.filter.OwnerFilter;
import com.paperassistant.service.RagService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.MediaType;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * RAG 检索 / 问答 / 摘要 / 综述 / 入库端点 — Python {@code src/api/main.py} 的
 * {@code /retrieve}、{@code /rag/*}、{@code /summarize}、{@code /survey}、
 * {@code /ingest*} 路由族。
 *
 * <p>阻塞调用（embedding 检索 / LLM 调用 / 文件 I/O）均通过
 * {@link Schedulers#boundedElastic()} 异步化，owner 隔离取自
 * {@link OwnerFilter#getOwnerId(ServerWebExchange)}。响应 JSON 字段沿用
 * Python 契约（全局 snake_case）。
 */
@RestController
public class RAGController {

    private static final Logger log = LoggerFactory.getLogger(RAGController.class);

    private final RagService ragService;

    public RAGController(RagService ragService) {
        this.ragService = ragService;
    }

    /** POST /retrieve — 混合检索，返回 {@code {"hits": [...], "query": ...}}。 */
    @PostMapping("/retrieve")
    public Mono<Map<String, Object>> retrieve(@RequestBody RetrieveRequest req,
                                              ServerWebExchange exchange) {
        String ownerId = OwnerFilter.getOwnerId(exchange);
        return Mono.fromCallable(() -> ragService.retrieve(req.getQuery(), req.getTopK(), ownerId))
                .subscribeOn(Schedulers.boundedElastic());
    }

    /** POST /rag/query — 非流式 RAG 问答，返回 {@code {"query","answer","sources"}}。 */
    @PostMapping("/rag/query")
    public Mono<Map<String, Object>> ragQuery(@RequestBody RAGQueryRequest req,
                                              ServerWebExchange exchange) {
        String ownerId = OwnerFilter.getOwnerId(exchange);
        return Mono.fromCallable(() ->
                        ragService.answerRag(req.getQuery(), req.getTopK(), req.getLang(), ownerId))
                .subscribeOn(Schedulers.boundedElastic());
    }

    /**
     * POST /rag/query/stream — SSE 流式 RAG 问答。
     *
     * <p>{@link RagService#answerRagStream} 返回的元素已经是 SSE 格式
     * （{@code data: <token>\n\n}）。Spring WebFlux 的 SSE 写出器会自行补一个
     * {@code data: } 前缀，因此这里先剥掉服务层预先加好的前缀，再包成
     * {@link ServerSentEvent}，最终线上输出恰好是 {@code data: <token>\n\n}
     * （与 Python 一致，前端 {@code line.slice(5)} 即可还原纯 token），末尾追加
     * {@code data: [DONE]\n\n}。
     */
    @PostMapping(value = "/rag/query/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public Flux<ServerSentEvent<String>> ragQueryStream(@RequestBody RAGQueryRequest req,
                                                        ServerWebExchange exchange) {
        String ownerId = OwnerFilter.getOwnerId(exchange);
        return ragService.answerRagStream(req.getQuery(), req.getTopK(), req.getLang(), ownerId)
                .map(event -> ServerSentEvent.<String>builder()
                        .data(unwrapSseData(event))
                        .build())
                .concatWith(Mono.just(ServerSentEvent.<String>builder().data("[DONE]").build()));
    }

    /** POST /summarize — 单篇论文摘要，返回 {@code {"summary": ...}}。 */
    @PostMapping("/summarize")
    public Mono<Map<String, String>> summarize(@RequestBody SummarizeRequest req) {
        return Mono.fromCallable(() -> {
            Map<String, String> result = new LinkedHashMap<>();
            result.put("summary", ragService.summarizePaper(req.getArxivId(), req.getLang()));
            return result;
        }).subscribeOn(Schedulers.boundedElastic());
    }

    /** POST /survey — 多文档综述，返回 {@code {"survey": ...}}。 */
    @PostMapping("/survey")
    public Mono<Map<String, String>> survey(@RequestBody SurveyRequest req,
                                            ServerWebExchange exchange) {
        String ownerId = OwnerFilter.getOwnerId(exchange);
        return Mono.fromCallable(() -> {
            Map<String, String> result = new LinkedHashMap<>();
            result.put("survey", ragService.survey(req.getQuery(), req.getTopK(), req.getLang(), ownerId));
            return result;
        }).subscribeOn(Schedulers.boundedElastic());
    }

    /** POST /ingest — 批量入库 parsed/ 目录（JSON），返回状态 map。 */
    @PostMapping("/ingest")
    public Mono<Map<String, Object>> ingest(@RequestBody IngestRequest req,
                                            ServerWebExchange exchange) {
        String ownerId = OwnerFilter.getOwnerId(exchange);
        return Mono.fromCallable(() -> ragService.ingestParsedDir(req.getParsedDir(), ownerId))
                .subscribeOn(Schedulers.boundedElastic());
    }

    /** POST /ingest-text — 单条文本直注入库，返回状态 map。 */
    @PostMapping("/ingest-text")
    public Mono<Map<String, Object>> ingestText(@RequestBody IngestTextRequest req,
                                                ServerWebExchange exchange) {
        String ownerId = OwnerFilter.getOwnerId(exchange);
        return Mono.fromCallable(() -> {
            Map<String, String> metadata = new LinkedHashMap<>();
            if (req.getMetadata() != null) {
                req.getMetadata().forEach((k, v) -> metadata.put(k, v == null ? null : String.valueOf(v)));
            }
            return ragService.ingestText(req.getText(), metadata, ownerId);
        }).subscribeOn(Schedulers.boundedElastic());
    }

    /**
     * 剥掉 {@code RagService} 已附加的 SSE 包装（{@code data: <token>\n\n}），
     * 还原出纯 token，交给 Spring 的 SSE 写出器统一加 {@code data: } 前缀。
     */
    private static String unwrapSseData(String event) {
        if (event == null) {
            return "";
        }
        String body = event;
        if (body.startsWith("data: ")) {
            body = body.substring("data: ".length());
        }
        return body.strip();
    }
}
