package com.paperassistant.controller;

import com.paperassistant.dto.request.AgentQueryRequest;
import com.paperassistant.dto.response.AgentQueryResponse;
import com.paperassistant.service.AgentService;
import org.springframework.http.MediaType;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;

/**
 * Agent 多步推理端点 — Python {@code src/api/main.py} 的 {@code /agent/*} 路由族。
 *
 * <ul>
 *   <li>{@code POST /agent/query} — 非流式：收集全部事件后返回 {@link AgentQueryResponse}；</li>
 *   <li>{@code POST /agent/query/stream} — SSE 流式：每个 {@code AgentEventResponse}
 *       发一条 {@code event: step\ndata: {json}\n\n}，最后追加
 *       {@code event: done\ndata: [DONE]\n\n}（与 Python 逐字节一致）。</li>
 * </ul>
 *
 * <p>阻塞调用（{@code runAgent}）走 {@link Schedulers#boundedElastic()}；
 * 流式方法 {@code runAgentStream} 自身已在 boundedElastic 上运行。
 */
@RestController
public class AgentController {

    private final AgentService agentService;

    public AgentController(AgentService agentService) {
        this.agentService = agentService;
    }

    /** POST /agent/query — 非流式 Agent 查询，返回完整 {@link AgentQueryResponse}。 */
    @PostMapping("/agent/query")
    public Mono<AgentQueryResponse> query(@RequestBody AgentQueryRequest req) {
        return Mono.fromCallable(() -> agentService.runAgent(
                        req.getQuery(), req.getLang(), req.getMaxIterations(), req.getEnabledTools()))
                .subscribeOn(Schedulers.boundedElastic());
    }

    /**
     * POST /agent/query/stream — SSE 流式 Agent 查询。
     *
     * <p>每个 {@code AgentEventResponse}（thinking / tool_call / tool_result /
     * answer_chunk / error / usage / done）发为一条 {@code event: step}，data 为
     * snake_case JSON（与 Python {@code json.dumps(event.model_dump())} 对齐）；
     * 末尾追加 {@code event: done\ndata: [DONE]\n\n}，前端据此结束流。
     */
    @PostMapping(value = "/agent/query/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public Flux<ServerSentEvent<?>> queryStream(@RequestBody AgentQueryRequest req) {
        return agentService.runAgentStream(
                        req.getQuery(), req.getLang(), req.getMaxIterations(), req.getEnabledTools())
                .<ServerSentEvent<?>>map(event -> ServerSentEvent.builder(event).event("step").build())
                .concatWith(Mono.just(ServerSentEvent.builder("[DONE]").event("done").build()));
    }
}
