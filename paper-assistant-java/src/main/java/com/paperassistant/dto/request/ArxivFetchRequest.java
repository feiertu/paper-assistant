package com.paperassistant.dto.request;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * arXiv 抓取请求（对应 Python {@code ArxivFetchRequest}）。
 *
 * <p>仅搜索并保存元数据，不下载/解析；{@code autoIngest} 由管道端点使用。
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class ArxivFetchRequest {

    @JsonProperty("query")
    private String query = "";

    @JsonProperty("max_results")
    @Min(1)
    @Max(50)
    private int maxResults = 5;

    @JsonProperty("auto_ingest")
    private boolean autoIngest = true;
}
