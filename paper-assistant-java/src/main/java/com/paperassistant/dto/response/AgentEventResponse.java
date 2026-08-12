package com.paperassistant.dto.response;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.Map;

/**
 * Agent 流式事件响应（对应 Python {@code AgentEvent}）。
 *
 * <p>{@code type} 取值：{@code thinking | tool_call | tool_result | answer_chunk |
 * error | usage | done}。{@code totalTokens}/{@code steps}/{@code durationMs} 仅部分事件类型携带。
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class AgentEventResponse {

    @JsonProperty("type")
    private String type;

    @JsonProperty("content")
    @Builder.Default
    private String content = "";

    @JsonProperty("tool")
    private String tool;

    @JsonProperty("args")
    private Map<String, Object> args;

    @JsonProperty("result")
    private String result;

    @JsonProperty("total_tokens")
    private Integer totalTokens;

    @JsonProperty("steps")
    private Integer steps;

    @JsonProperty("duration_ms")
    private Integer durationMs;

    @JsonProperty("message")
    private String message;
}
