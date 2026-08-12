package com.paperassistant.llm;

import com.paperassistant.config.AppConfig;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.SystemMessage;
import org.springframework.ai.chat.messages.UserMessage;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.model.function.FunctionCallback;
import org.springframework.ai.openai.OpenAiChatOptions;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;
import reactor.core.publisher.Flux;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * Unified wrapper around Spring AI {@link ChatClient}, mirroring the Python
 * {@code src/llm/client.py} {@code LLMClient}. This is the single entry point
 * for every LLM interaction in the rewrite (RAG Q&A, summaries, surveys, and
 * the future Agent loop), so callers never touch {@link ChatClient} directly.
 *
 * <p><b>Availability:</b> the wrapped {@link ChatClient} is <em>nullable</em>.
 * It is only built when {@link AppConfig#openaiApiKey()} is configured (the same
 * pattern as {@code RagService} / {@code EmbedService}). Every public method
 * guards with {@link #requireChatClient()} and throws a clear
 * {@link IllegalStateException} when the API key is absent, so the app can boot
 * without an LLM and fail only when an LLM-backed feature is actually used.
 *
 * <p><b>Three call styles:</b>
 * <ul>
 *   <li>{@link #chat} — non-streaming completion returning the assistant text;
 *       responses are memoized in the {@code llmCache} Caffeine cache (keyed by
 *       model, temperature, and the serialized message list, mirroring Python's
 *       {@code make_llm_key}).</li>
 *   <li>{@link #chatStream} — streaming completion returning a cold
 *       {@link Flux}{@code <String>} where each element is one token. Streaming
 *       is intentionally <em>not</em> cached.</li>
 *   <li>{@link #chatRaw} — non-streaming completion returning the full
 *       {@link ChatResponse} so the Agent loop can inspect {@code tool_calls}
 *       (via {@code response.getResult().getOutput().getToolCalls()}) and decide
 *       what to execute. Tool auto-execution is disabled so the raw tool calls
 *       reach the caller unchanged.</li>
 * </ul>
 *
 * <p><b>Logging contract:</b> every call logs the model name, message count,
 * and response length — never the message content.
 */
@Service
public class ChatClientService {

    private static final Logger log = LoggerFactory.getLogger(ChatClientService.class);

    /** Nullable — only built when {@link AppConfig#openaiApiKey()} is configured. */
    private final ChatClient chatClient;
    private final AppConfig config;

    public ChatClientService(AppConfig config,
                             ObjectProvider<ChatClient.Builder> chatClientBuilderProvider) {
        this.config = config;
        this.chatClient = buildChatClient(chatClientBuilderProvider);
        log.info("ChatClientService initialized: llmModel={} chatClient={}",
                config.llmModel(),
                chatClient != null ? "available" : "absent (no API key)");
    }

    // ──────────────────────────────────────────────
    //  Non-streaming chat
    // ──────────────────────────────────────────────

    /**
     * Basic non-streaming chat completion, returning the assistant text
     * (Python {@code LLMClient.chat}).
     *
     * <p>Responses are cached in the {@code llmCache} Caffeine cache. The cache
     * key is the {@code (model, temperature, messages)} triple, so identical
     * requests short-circuit to the stored answer — the same intent as Python's
     * {@code make_llm_key()}. Pass {@code null} for {@code model} /
     * {@code temperature} to fall back to the configured defaults.
     *
     * @param messages    ordered role/content pairs ({@code role} in
     *                    {@code system | user | assistant})
     * @param model       model name, or {@code null}/{@code blank} for
     *                    {@link AppConfig#llmModel()}
     * @param temperature sampling temperature, or {@code null} for
     *                    {@link AppConfig#llmTemperature()}
     * @return the assistant text (may be {@code null} if the model streams no
     *         content — callers should guard against it)
     */
    @Cacheable(cacheNames = "llmCache", key = "#model + '|' + #temperature + '|' + #messages")
    public String chat(List<Map<String, String>> messages, String model, Double temperature) {
        ChatClient client = requireChatClient();
        requireMessages(messages);

        String effectiveModel = StringUtils.hasText(model) ? model : config.llmModel();
        double effectiveTemperature = temperature != null ? temperature : config.llmTemperature();
        log.info("LLM chat: model={} messages={} temperature={}",
                effectiveModel, messages.size(), effectiveTemperature);

        String content = client.prompt()
                .messages(toMessages(messages))
                .options(OpenAiChatOptions.builder()
                        .model(effectiveModel)
                        .temperature(effectiveTemperature)
                        .maxTokens(config.llmMaxTokens())
                        .build())
                .call()
                .content();

        log.info("LLM chat done: model={} response_len={}",
                effectiveModel, content != null ? content.length() : 0);
        return content;
    }

    // ──────────────────────────────────────────────
    //  Streaming chat
    // ──────────────────────────────────────────────

    /**
     * Streaming chat completion (Python {@code LLMClient.chat_stream}). Returns
     * a cold {@link Flux}{@code <String>} where each element is one token.
     *
     * <p>Streaming is deliberately <em>not</em> cached — a token stream cannot
     * be replay-served from a cache without buffering the whole answer, which
     * would defeat streaming's latency benefit (Python's stream path is likewise
     * cache-free).
     *
     * @param messages ordered role/content pairs
     * @param model    model name, or {@code null}/{@code blank} for
     *                 {@link AppConfig#llmModel()}
     * @return cold token {@link Flux} — subscribe to begin streaming
     */
    public Flux<String> chatStream(List<Map<String, String>> messages, String model) {
        ChatClient client = requireChatClient();
        requireMessages(messages);

        String effectiveModel = StringUtils.hasText(model) ? model : config.llmModel();
        log.info("LLM chatStream: model={} messages={}", effectiveModel, messages.size());

        return client.prompt()
                .messages(toMessages(messages))
                .options(OpenAiChatOptions.builder()
                        .model(effectiveModel)
                        .temperature(config.llmTemperature())
                        .maxTokens(config.llmMaxTokens())
                        .build())
                .stream()
                .content();
    }

    // ──────────────────────────────────────────────
    //  Raw chat with tools (Agent loop)
    // ──────────────────────────────────────────────

    /**
     * Non-streaming chat returning the full {@link ChatResponse} rather than the
     * plain text (Python {@code LLMClient.chat_raw}). Intended for the Agent
     * loop, which needs the raw {@code tool_calls} to decide what to execute.
     *
     * <p>Tool <em>auto-execution</em> is disabled
     * ({@code internalToolExecutionEnabled(false)}), so the response's
     * {@code AssistantMessage.getToolCalls()} always contains the un-executed
     * tool calls when the model asks for a tool — the caller decides when and how
     * to run them and then feeds the result back as a follow-up message.
     *
     * <p>Uses the Agent-specific model/temperature
     * ({@link AppConfig#effectiveLlmAgentModel()}, {@link AppConfig#agentTemperature()})
     * since this method exists for the Agent loop.
     *
     * @param messages ordered role/content pairs
     * @param tools    function callbacks exposed to the model (may be empty)
     * @return the raw {@link ChatResponse}; inspect
     *         {@code response.getResult().getOutput().getToolCalls()} for tool calls
     */
    public ChatResponse chatRaw(List<Map<String, String>> messages, List<FunctionCallback> tools) {
        ChatClient client = requireChatClient();
        requireMessages(messages);

        List<FunctionCallback> toolList = tools != null ? tools : List.of();
        String model = config.effectiveLlmAgentModel();
        double temperature = config.agentTemperature();
        log.info("LLM chatRaw: model={} messages={} tools={}",
                model, messages.size(), toolList.size());

        return client.prompt()
                .messages(toMessages(messages))
                .options(OpenAiChatOptions.builder()
                        .model(model)
                        .temperature(temperature)
                        .maxTokens(config.llmMaxTokens())
                        .internalToolExecutionEnabled(false)
                        .build())
                .tools(toolList.toArray(new FunctionCallback[0]))
                .call()
                .chatResponse();
    }

    // ──────────────────────────────────────────────
    //  Public helpers
    // ──────────────────────────────────────────────

    /**
     * Convenience builder for a {@code [system, user]} message list, skipping
     * the system entry when it is {@code null}/{@code blank} (mirrors Python
     * callers that pass only a user prompt, e.g. summary/survey).
     *
     * @param system system prompt, or {@code null}/{@code blank} to omit it
     * @param user   user prompt (may be {@code null}, stored as empty string)
     * @return mutable {@code List<Map<String,String>>} of {@code role/content} maps
     */
    public static List<Map<String, String>> messages(String system, String user) {
        List<Map<String, String>> result = new ArrayList<>(2);
        if (system != null && !system.isBlank()) {
            result.add(Map.of("role", "system", "content", system));
        }
        result.add(Map.of("role", "user", "content", user != null ? user : ""));
        return result;
    }

    // ──────────────────────────────────────────────
    //  Private helpers
    // ──────────────────────────────────────────────

    /**
     * Returns the {@link ChatClient} or throws a clear {@link IllegalStateException}
     * when it was never built (missing API key).
     */
    private ChatClient requireChatClient() {
        if (chatClient == null) {
            throw new IllegalStateException(
                    "OpenAI API key is not configured (set OPENAI_API_KEY env var or "
                            + "paper-assistant.openai-api-key). The LLM-backed methods "
                            + "(chat, chatStream, chatRaw) require it.");
        }
        return chatClient;
    }

    /**
     * Builds the {@link ChatClient} from Spring AI's auto-configured builder,
     * only when an API key is present — otherwise stores {@code null}.
     */
    private ChatClient buildChatClient(ObjectProvider<ChatClient.Builder> provider) {
        if (!StringUtils.hasText(config.openaiApiKey())) {
            log.warn("No OpenAI API key configured — LLM methods will be unavailable");
            return null;
        }
        ChatClient.Builder builder = provider.getIfAvailable();
        if (builder == null) {
            log.warn("ChatClient.Builder bean is not available (check spring-ai-openai dependency "
                    + "and api-key config) — LLM methods will be unavailable");
            return null;
        }
        return builder.build();
    }

    /**
     * Validates a non-null, non-empty message list. Chat completions require at
     * least one message; failing early keeps the error local to the call site.
     */
    private static void requireMessages(List<Map<String, String>> messages) {
        if (messages == null || messages.isEmpty()) {
            throw new IllegalArgumentException("messages must not be null or empty");
        }
    }

    /**
     * Converts the public {@code {role, content}} maps into Spring AI
     * {@link Message} objects. Roles {@code system}/{@code assistant}/{@code user}
     * map to {@link SystemMessage}/{@link AssistantMessage}/{@link UserMessage};
     * any other role is treated as {@code user} with a warning.
     *
     * <p>Note: assistant entries carrying {@code tool_calls} are not yet handled
     * here — that parsing belongs to the Agent task, which will feed tool results
     * back as {@code tool} messages directly.
     */
    private static List<Message> toMessages(List<Map<String, String>> messages) {
        List<Message> out = new ArrayList<>(messages.size());
        for (Map<String, String> m : messages) {
            String role = m.getOrDefault("role", "user");
            String content = m.getOrDefault("content", "");
            switch (role) {
                case "system" -> out.add(new SystemMessage(content));
                case "assistant" -> out.add(new AssistantMessage(content));
                case "user" -> out.add(new UserMessage(content));
                default -> {
                    log.warn("Unknown message role '{}', treating as user", role);
                    out.add(new UserMessage(content));
                }
            }
        }
        return out;
    }
}
