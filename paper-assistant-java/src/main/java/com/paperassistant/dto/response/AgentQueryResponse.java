package com.paperassistant.dto.response;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.ArrayList;
import java.util.List;

/**
 * Agent 查询响应（非流式，对应 Python {@code AgentQueryResponse}）。
 *
 * <p>{@code reasoningSteps} 为推理事件列表，缺省空表。
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class AgentQueryResponse {

    @JsonProperty("query")
    private String query;

    @JsonProperty("answer")
    private String answer;

    @JsonProperty("reasoning_steps")
    @Builder.Default
    private List<AgentEventResponse> reasoningSteps = new ArrayList<>();

    @JsonProperty("iterations")
    @Builder.Default
    private int iterations = 0;

    @JsonProperty("total_tokens")
    @Builder.Default
    private int totalTokens = 0;

    @JsonProperty("duration_ms")
    @Builder.Default
    private int durationMs = 0;
}
