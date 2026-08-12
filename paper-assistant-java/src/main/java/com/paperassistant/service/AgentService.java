package com.paperassistant.service;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.paperassistant.agent.AgentTools;
import com.paperassistant.config.AppConfig;
import com.paperassistant.dto.response.AgentEventResponse;
import com.paperassistant.dto.response.AgentQueryResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.SystemMessage;
import org.springframework.ai.chat.messages.ToolResponseMessage;
import org.springframework.ai.chat.messages.UserMessage;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.model.function.FunctionCallback;
import org.springframework.ai.openai.OpenAiChatOptions;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;
import reactor.core.publisher.Flux;
import reactor.core.publisher.FluxSink;
import reactor.core.scheduler.Schedulers;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * ReAct agent service — manual tool-use loop with SSE streaming over WebFlux.
 *
 * <p>Uses Spring AI {@link ChatClient} directly for full control over multi-turn
 * message history (including tool-call and tool-result messages), building
 * {@link FunctionCallback} instances from the {@link AgentTools} component.
 *
 * <p><b>Streaming:</b> {@link #runAgentStream} returns a {@link Flux}{@code <AgentEventResponse>}
 * following the SSE event sequence: thinking → tool_call → tool_result → answer_chunk → usage → done.
 *
 * <p><b>Non-streaming:</b> {@link #runAgent} collects all events into an {@link AgentQueryResponse}.
 */
@Service
public class AgentService {

    private static final Logger log = LoggerFactory.getLogger(AgentService.class);

    /** Max characters of tool result to include in conversation history. */
    private static final int MAX_TOOL_RESULT_CHARS = 4000;

    private final AgentTools agentTools;
    private final AppConfig config;
    private final ChatClient chatClient;
    private final ObjectMapper objectMapper;

    public AgentService(AgentTools agentTools,
                        AppConfig config,
                        ObjectMapper objectMapper,
                        ObjectProvider<ChatClient.Builder> chatClientBuilderProvider) {
        this.agentTools = agentTools;
        this.config = config;
        this.objectMapper = objectMapper;
        this.chatClient = buildChatClient(chatClientBuilderProvider);
        log.info("AgentService initialized: model={} maxIterations={} chatClient={}",
                config.effectiveLlmAgentModel(), config.agentMaxIterations(),
                chatClient != null ? "available" : "absent");
    }

    // ──────────────────────────────────────────────
    //  Public API
    // ──────────────────────────────────────────────

    /**
     * Runs the agent in streaming mode, emitting SSE events via a {@link Flux}.
     *
     * @param query          user question
     * @param lang           "zh" or "en"
     * @param maxIterations  max agent steps (0 = config default)
     * @param enabledTools   enabled tool names; null or empty = all tools
     * @return cold SSE event flux
     */
    public Flux<AgentEventResponse> runAgentStream(String query, String lang,
                                                    int maxIterations,
                                                    List<String> enabledTools) {
        if (chatClient == null) {
            return Flux.just(errorEvent("OpenAI API key is not configured"));
        }

        int iterations = maxIterations > 0 ? Math.min(maxIterations, config.agentMaxIterations()) : config.agentMaxIterations();
        List<String> effectiveTools = (enabledTools == null || enabledTools.isEmpty())
                ? ALL_TOOL_NAMES
                : enabledTools.stream().filter(ALL_TOOL_NAMES::contains).toList();

        return Flux.<AgentEventResponse>create(sink -> {
            long startMs = System.currentTimeMillis();
            try {
                doRunAgent(query, lang, iterations, effectiveTools, sink, startMs);
            } catch (Exception e) {
                log.error("Agent loop error: {}", e.getMessage(), e);
                sink.next(errorEvent("Agent 执行异常: " + e.getMessage()));
                completeSink(sink, 0, 0, (int) (System.currentTimeMillis() - startMs));
            }
        }, FluxSink.OverflowStrategy.BUFFER)
                .subscribeOn(Schedulers.boundedElastic());
    }

    /**
     * Non-streaming agent execution — collects events and assembles the final response.
     */
    public AgentQueryResponse runAgent(String query, String lang,
                                        int maxIterations,
                                        List<String> enabledTools) {
        long startMs = System.currentTimeMillis();
        int totalTokens = 0;
        int steps = 0;
        List<AgentEventResponse> reasoningSteps = new ArrayList<>();
        StringBuilder answerBuilder = new StringBuilder();

        if (chatClient == null) {
            return AgentQueryResponse.builder()
                    .query(query)
                    .answer("OpenAI API key is not configured")
                    .durationMs(0)
                    .build();
        }

        int iterations = maxIterations > 0 ? Math.min(maxIterations, config.agentMaxIterations()) : config.agentMaxIterations();
        List<String> effectiveTools = (enabledTools == null || enabledTools.isEmpty())
                ? ALL_TOOL_NAMES
                : enabledTools.stream().filter(ALL_TOOL_NAMES::contains).toList();

        try {
            AgentLoopResult result = runAgentLoop(query, lang, iterations, effectiveTools,
                    event -> {
                        reasoningSteps.add(event);
                        if ("answer_chunk".equals(event.getType()) && StringUtils.hasText(event.getContent())) {
                            answerBuilder.append(event.getContent());
                        }
                        if (event.getTotalTokens() != null) {
                            // track last usage event
                        }
                    });

            totalTokens = result.totalTokens();
            steps = result.steps();
        } catch (Exception e) {
            log.error("Agent loop error: {}", e.getMessage(), e);
            answerBuilder.append("Agent 执行异常: ").append(e.getMessage());
        }

        int durationMs = (int) (System.currentTimeMillis() - startMs);
        return AgentQueryResponse.builder()
                .query(query)
                .answer(answerBuilder.toString())
                .reasoningSteps(reasoningSteps)
                .iterations(steps)
                .totalTokens(totalTokens)
                .durationMs(durationMs)
                .build();
    }

    // ──────────────────────────────────────────────
    //  Agent loop (shared by streaming and non-streaming)
    // ──────────────────────────────────────────────

    /**
     * Callback for each event emitted during the agent loop.
     */
    @FunctionalInterface
    private interface EventConsumer {
        void accept(AgentEventResponse event);
    }

    /**
     * Result of the agent loop.
     */
    private record AgentLoopResult(int totalTokens, int steps) {}

    /**
     * Core ReAct loop pushing events into the sink.
     */
    private void doRunAgent(String query, String lang, int maxIterations,
                            List<String> enabledTools,
                            FluxSink<AgentEventResponse> sink, long startMs) {
        int[] totalTokens = {0};
        int[] steps = {0};

        try {
            AgentLoopResult result = runAgentLoop(query, lang, maxIterations, enabledTools,
                    event -> sink.next(event));
            totalTokens[0] = result.totalTokens();
            steps[0] = result.steps();
        } catch (Exception e) {
            log.error("Agent loop error: {}", e.getMessage(), e);
            sink.next(errorEvent("Agent 执行异常: " + e.getMessage()));
        }

        completeSink(sink, totalTokens[0], steps[0],
                (int) (System.currentTimeMillis() - startMs));
    }

    /**
     * Implements the ReAct loop: build tools → loop(chat → execute tools → repeat).
     *
     * @return {@link AgentLoopResult} with total tokens and steps
     */
    private AgentLoopResult runAgentLoop(String query, String lang, int maxIterations,
                                          List<String> enabledTools,
                                          EventConsumer eventSink) {
        int totalTokens = 0;
        int step = 0;

        // 1) Build system prompt
        String systemPrompt = buildSystemPrompt(lang, enabledTools);

        // 2) Build tool callbacks
        List<FunctionCallback> toolCallbacks = buildToolCallbacks(enabledTools);

        // 3) Message history
        List<Message> messages = new ArrayList<>();
        messages.add(new SystemMessage(systemPrompt));
        messages.add(new UserMessage(query));

        // 4) Emit initial thinking event
        eventSink.accept(AgentEventResponse.builder()
                .type("thinking")
                .content("开始分析用户问题…（最多 " + maxIterations + " 步）")
                .build());

        String effectiveModel = config.effectiveLlmAgentModel();
        double temperature = config.agentTemperature();

        // 5) ReAct loop
        for (step = 1; step <= maxIterations; step++) {
            // Emit thinking event for this step
            eventSink.accept(AgentEventResponse.builder()
                    .type("thinking")
                    .content("第 " + step + "/" + maxIterations + " 步推理中…")
                    .build());

            // Call LLM with tools
            ChatResponse response;
            try {
                response = chatClient.prompt()
                        .messages(messages)
                        .options(OpenAiChatOptions.builder()
                                .model(effectiveModel)
                                .temperature(temperature)
                                .maxTokens(config.llmMaxTokens())
                                .internalToolExecutionEnabled(false)
                                .build())
                        .tools(toolCallbacks.toArray(new FunctionCallback[0]))
                        .call()
                        .chatResponse();
            } catch (Exception e) {
                log.error("LLM call failed at step {}: {}", step, e.getMessage());
                eventSink.accept(errorEvent("LLM 调用失败: " + e.getMessage()));
                return new AgentLoopResult(totalTokens, step);
            }

            // Track token usage
            if (response.getMetadata() != null && response.getMetadata().getUsage() != null) {
                var usage = response.getMetadata().getUsage();
                totalTokens += (int) usage.getTotalTokens();
            }

            AssistantMessage assistantMsg = response.getResult().getOutput();
            List<AssistantMessage.ToolCall> toolCalls = assistantMsg.getToolCalls();

            if (toolCalls != null && !toolCalls.isEmpty()) {
                // --- Tool call path ---
                // Add assistant message (with tool calls) to history
                messages.add(assistantMsg);

                List<ToolResponseMessage.ToolResponse> toolResponses = new ArrayList<>();

                for (AssistantMessage.ToolCall tc : toolCalls) {
                    String toolName = tc.name();
                    String rawArgs = tc.arguments();

                    // Emit tool_call event
                    Map<String, Object> argsMap = parseArgs(rawArgs);
                    eventSink.accept(AgentEventResponse.builder()
                            .type("tool_call")
                            .tool(toolName)
                            .args(argsMap)
                            .build());

                    // Execute the tool
                    String toolResult = executeTool(toolName, argsMap);
                    if (toolResult != null && toolResult.length() > MAX_TOOL_RESULT_CHARS) {
                        toolResult = toolResult.substring(0, MAX_TOOL_RESULT_CHARS) + "…[已截断]";
                    }

                    // Emit tool_result event
                    eventSink.accept(AgentEventResponse.builder()
                            .type("tool_result")
                            .tool(toolName)
                            .result(toolResult)
                            .build());

                    // Build ToolResponse for the conversation
                    toolResponses.add(new ToolResponseMessage.ToolResponse(
                            tc.id(), toolName, toolResult));
                }

                // Add tool response message to history
                messages.add(new ToolResponseMessage(toolResponses, Map.of()));

                log.info("Agent step {}: executed {} tool(s)", step, toolCalls.size());
            } else {
                // --- Text answer path ---
                String textContent = assistantMsg.getText();
                if (StringUtils.hasText(textContent)) {
                    // Add assistant message to history
                    messages.add(assistantMsg);

                    // Emit answer as chunks (simulated streaming — emit whole text as one chunk)
                    eventSink.accept(AgentEventResponse.builder()
                            .type("answer_chunk")
                            .content(textContent)
                            .build());
                }

                // Agent decided to finish
                log.info("Agent finished at step {}: answer_len={}",
                        step, textContent != null ? textContent.length() : 0);
                break;
            }
        }

        // If we exhausted all iterations, note it
        if (step > maxIterations) {
            eventSink.accept(AgentEventResponse.builder()
                    .type("thinking")
                    .content("已达到最大推理步数（" + maxIterations + "），任务终止。")
                    .build());
        }

        return new AgentLoopResult(totalTokens, step);
    }

    // ──────────────────────────────────────────────
    //  Tool execution
    // ──────────────────────────────────────────────

    /**
     * Executes a tool by name with the given arguments map.
     */
    private String executeTool(String name, Map<String, Object> args) {
        try {
            return switch (name) {
                case "search" -> agentTools.search(
                        strArg(args, "query"),
                        strArg(args, "mode"),
                        intArg(args, "top_k"),
                        strArg(args, "author"),
                        strArg(args, "year_from"),
                        strArg(args, "year_to"));
                case "getPaper" -> agentTools.getPaper(
                        strArg(args, "arxiv_id"));
                case "summarizePaper" -> agentTools.summarizePaper(
                        strArg(args, "arxiv_id"),
                        strArg(args, "lang"));
                case "getCitations" -> agentTools.getCitations(
                        strArg(args, "arxiv_id"));
                case "comparePapers" -> agentTools.comparePapers(
                        strArg(args, "arxiv_id1"),
                        strArg(args, "arxiv_id2"),
                        strArg(args, "lang"));
                case "recommendSimilar" -> agentTools.recommendSimilar(
                        strArg(args, "arxiv_id"),
                        intArg(args, "top_k"));
                case "generateSurvey" -> agentTools.generateSurvey(
                        strArg(args, "topic"),
                        strArg(args, "mode"),
                        intArg(args, "top_k"),
                        strArg(args, "lang"),
                        strArg(args, "fmt"));
                default -> "未知工具: " + name;
            };
        } catch (Exception e) {
            log.error("Tool execution failed: {}: {}", name, e.getMessage());
            return "工具执行异常: " + e.getMessage();
        }
    }

    // ──────────────────────────────────────────────
    //  FunctionCallback construction
    // ──────────────────────────────────────────────

    /** All 7 tool names (order matches Python agent). */
    private static final List<String> ALL_TOOL_NAMES = List.of(
            "search", "getPaper", "summarizePaper", "getCitations",
            "comparePapers", "recommendSimilar", "generateSurvey"
    );

    /**
     * Builds {@link FunctionCallback} instances for the enabled tools.
     *
     * <p>Each callback wraps an {@link AgentTools} method. The input schema is
     * defined as a static JSON string matching the OpenAI function calling format
     * with parameter definitions derived from each tool's input record.
     */
    private List<FunctionCallback> buildToolCallbacks(List<String> enabledTools) {
        List<FunctionCallback> callbacks = new ArrayList<>();

        if (enabledTools.contains("search")) {
            callbacks.add(createCallback("search",
                    "搜索论文。支持三种模式: fts(全文搜索含关键词、作者、年份过滤), semantic(语义向量搜索), list(列出最近全部论文)",
                    SEARCH_SCHEMA));
        }
        if (enabledTools.contains("getPaper")) {
            callbacks.add(createCallback("getPaper",
                    "获取指定 arXiv ID 论文的完整元数据（标题、作者、摘要、发表日期等）",
                    GET_PAPER_SCHEMA));
        }
        if (enabledTools.contains("summarizePaper")) {
            callbacks.add(createCallback("summarizePaper",
                    "对指定论文生成结构化摘要（三段式：研究问题/方法/结论与意义）",
                    SUMMARIZE_SCHEMA));
        }
        if (enabledTools.contains("getCitations")) {
            callbacks.add(createCallback("getCitations",
                    "获取论文的引用关系图，包括该论文引用了哪些论文（cites）以及被哪些论文引用（cited_by）",
                    GET_CITATIONS_SCHEMA));
        }
        if (enabledTools.contains("comparePapers")) {
            callbacks.add(createCallback("comparePapers",
                    "对比两篇论文的异同，从研究问题、方法、实验结果、结论四个维度进行结构化对比分析",
                    COMPARE_SCHEMA));
        }
        if (enabledTools.contains("recommendSimilar")) {
            callbacks.add(createCallback("recommendSimilar",
                    "基于向量相似度推荐与指定论文最相似的论文",
                    RECOMMEND_SCHEMA));
        }
        if (enabledTools.contains("generateSurvey")) {
            callbacks.add(createCallback("generateSurvey",
                    "生成多论文综述或导出论文数据。mode=survey 用 LLM 自动撰写综述，mode=export 导出论文列表（支持 json 或 text 格式）",
                    SURVEY_SCHEMA));
        }

        return callbacks;
    }

    /**
     * Creates a {@link FunctionCallback} with a manual JSON Schema.
     */
    private FunctionCallback createCallback(String name, String description, String schemaJson) {
        return new FunctionCallback() {
            @Override
            public String getName() {
                return name;
            }

            @Override
            public String getDescription() {
                return description;
            }

            @Override
            public String getInputTypeSchema() {
                return schemaJson;
            }

            @Override
            public String call(String functionArguments) {
                // This is handled by the agent loop directly via executeTool()
                // The framework may call this, so delegate to executeTool
                Map<String, Object> args = parseArgs(functionArguments);
                return executeTool(name, args);
            }
        };
    }

    // ──────────────────────────────────────────────
    //  JSON Schemas (OpenAI function calling format)
    // ──────────────────────────────────────────────

    private static final String SEARCH_SCHEMA = """
            {
              "type": "object",
              "properties": {
                "query": {"type": "string", "description": "搜索关键词或论文标题"},
                "mode": {"type": "string", "description": "搜索模式: fts(全文搜索), semantic(语义搜索), list(列出全部)", "enum": ["fts", "semantic", "list"]},
                "top_k": {"type": "integer", "description": "返回结果数量，默认10"},
                "author": {"type": "string", "description": "按作者过滤，可选"},
                "year_from": {"type": "string", "description": "起始发表年份，可选"},
                "year_to": {"type": "string", "description": "结束发表年份，可选"}
              },
              "required": ["query"]
            }""";

    private static final String GET_PAPER_SCHEMA = """
            {
              "type": "object",
              "properties": {
                "arxiv_id": {"type": "string", "description": "论文 arXiv ID，如 2301.12345"}
              },
              "required": ["arxiv_id"]
            }""";

    private static final String SUMMARIZE_SCHEMA = """
            {
              "type": "object",
              "properties": {
                "arxiv_id": {"type": "string", "description": "论文 arXiv ID"},
                "lang": {"type": "string", "description": "语言: zh(中文) 或 en(英文)", "enum": ["zh", "en"]}
              },
              "required": ["arxiv_id"]
            }""";

    private static final String GET_CITATIONS_SCHEMA = """
            {
              "type": "object",
              "properties": {
                "arxiv_id": {"type": "string", "description": "论文 arXiv ID"}
              },
              "required": ["arxiv_id"]
            }""";

    private static final String COMPARE_SCHEMA = """
            {
              "type": "object",
              "properties": {
                "arxiv_id1": {"type": "string", "description": "第一篇论文 arXiv ID"},
                "arxiv_id2": {"type": "string", "description": "第二篇论文 arXiv ID"},
                "lang": {"type": "string", "description": "语言: zh 或 en", "enum": ["zh", "en"]}
              },
              "required": ["arxiv_id1", "arxiv_id2"]
            }""";

    private static final String RECOMMEND_SCHEMA = """
            {
              "type": "object",
              "properties": {
                "arxiv_id": {"type": "string", "description": "参考论文 arXiv ID"},
                "top_k": {"type": "integer", "description": "返回相似论文数量，默认5"}
              },
              "required": ["arxiv_id"]
            }""";

    private static final String SURVEY_SCHEMA = """
            {
              "type": "object",
              "properties": {
                "topic": {"type": "string", "description": "综述主题"},
                "mode": {"type": "string", "description": "模式: survey(生成综述) 或 export(导出论文列表)", "enum": ["survey", "export"]},
                "top_k": {"type": "integer", "description": "检索论文数量，默认10"},
                "lang": {"type": "string", "description": "语言: zh 或 en", "enum": ["zh", "en"]},
                "fmt": {"type": "string", "description": "导出格式: json 或 text", "enum": ["json", "text"]}
              },
              "required": ["topic"]
            }""";

    // ──────────────────────────────────────────────
    //  System prompt
    // ──────────────────────────────────────────────

    private String buildSystemPrompt(String lang, List<String> enabledTools) {
        String toolList = String.join(", ", enabledTools);
        if ("en".equalsIgnoreCase(lang)) {
            return """
                    You are an academic paper research assistant with access to a paper database.
                    You can use the following tools to help users find, read, compare, and analyze academic papers.

                    Available tools: """ + toolList + """

                    Guidelines:
                    1. First understand the user's question, then choose the appropriate tool(s).
                    2. For paper searches, if the user asks broadly, use "semantic" mode; for specific keywords/authors, use "fts" mode.
                    3. When the user asks about a specific paper, use getPaper to check availability and then
                       use summarizePaper or getCitations as needed.
                    4. When comparing papers, make sure both papers exist before calling comparePapers.
                    5. For survey requests, use generateSurvey with mode="survey".
                    6. Use recommendSimilar after analyzing a paper if the user wants related work.
                    7. Answer in English unless the user specifies otherwise.
                    8. Always verify paper existence before summarizing or comparing.
                    9. Think step by step — plan which tools to use before calling them.
                    """;
        } else {
            return """
                    你是一个学术论文研究助手，可以访问论文数据库。
                    你可以使用以下工具帮助用户查找、阅读、对比和分析学术论文。

                    可用工具：""" + toolList + """

                    指导原则：
                    1. 先理解用户问题，再选择合适工具。
                    2. 搜索论文时：宽泛问题用 semantic 模式，具体关键词/作者用 fts 模式。
                    3. 查看特定论文前先用 getPaper 确认存在，再按需调用 summarizePaper 或 getCitations。
                    4. 对比论文前确保两篇论文都存在。
                    5. 生成综述用 generateSurvey mode="survey"。
                    6. 分析完一篇论文后如用户想找相关工作，用 recommendSimilar。
                    7. 回答简洁专业，用中文回复。
                    8. 做摘要或对比前务必确认论文存在。
                    9. 逐步思考——调用工具前规划好步骤。
                    """;
        }
    }

    // ──────────────────────────────────────────────
    //  Helpers
    // ──────────────────────────────────────────────

    /** Parses JSON function arguments into a string-keyed map. */
    private Map<String, Object> parseArgs(String rawArgs) {
        if (rawArgs == null || rawArgs.isBlank()) {
            return Map.of();
        }
        try {
            @SuppressWarnings("unchecked")
            Map<String, Object> result = objectMapper.readValue(rawArgs, Map.class);
            return result;
        } catch (JsonProcessingException e) {
            log.warn("Failed to parse tool args JSON: {}", rawArgs);
            return Map.of();
        }
    }

    private static String strArg(Map<String, Object> args, String key) {
        Object value = args.get(key);
        return value != null ? value.toString() : "";
    }

    private static int intArg(Map<String, Object> args, String key) {
        Object value = args.get(key);
        if (value instanceof Number n) {
            return n.intValue();
        }
        if (value instanceof String s) {
            try {
                return Integer.parseInt(s);
            } catch (NumberFormatException e) {
                return 0;
            }
        }
        return 0;
    }

    private AgentEventResponse errorEvent(String message) {
        return AgentEventResponse.builder()
                .type("error")
                .content(message)
                .build();
    }

    private void completeSink(FluxSink<AgentEventResponse> sink,
                               int totalTokens, int steps, int durationMs) {
        sink.next(AgentEventResponse.builder()
                .type("usage")
                .totalTokens(totalTokens)
                .steps(steps)
                .durationMs(durationMs)
                .build());
        sink.next(AgentEventResponse.builder()
                .type("done")
                .build());
        sink.complete();
    }

    private ChatClient buildChatClient(ObjectProvider<ChatClient.Builder> provider) {
        if (!StringUtils.hasText(config.openaiApiKey())) {
            log.warn("No OpenAI API key configured — Agent will be unavailable");
            return null;
        }
        ChatClient.Builder builder = provider.getIfAvailable();
        if (builder == null) {
            log.warn("ChatClient.Builder bean is not available — Agent will be unavailable");
            return null;
        }
        return builder.build();
    }
}
