package com.paperassistant.dto.request;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * arXiv 一键管道请求（对应 Python {@code ArxivPipelineRequest}）。
 *
 * <p>搜索 → 下载 → 解析 → 入库；{@code autoIngest} 为 false 时仅保存元数据。
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class ArxivPipelineRequest {

    @JsonProperty("query")
    private String query = "";

    @JsonProperty("max_results")
    @Min(1)
    @Max(50)
    private int maxResults = 5;

    @JsonProperty("auto_ingest")
    private boolean autoIngest = true;
}
