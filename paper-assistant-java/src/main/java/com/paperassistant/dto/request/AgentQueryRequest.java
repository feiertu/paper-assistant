package com.paperassistant.dto.request;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

/**
 * Agent 查询请求（对应 Python {@code AgentQueryRequest}）。
 *
 * <p>{@code enabledTools} 为 null 表示全部工具启用（Python：None = 全部启用）。
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class AgentQueryRequest {

    @JsonProperty("query")
    private String query;

    @JsonProperty("lang")
    private String lang = "zh";

    @JsonProperty("max_iterations")
    @Min(1)
    @Max(30)
    private int maxIterations = 10;

    @JsonProperty("enabled_tools")
    private List<String> enabledTools;
}
