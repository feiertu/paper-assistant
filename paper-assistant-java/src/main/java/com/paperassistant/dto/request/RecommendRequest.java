package com.paperassistant.dto.request;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 相似论文推荐请求（对应 Python {@code RecommendRequest}）。
 *
 * <p>{@code top_k} 默认 5，范围 [1, 20]。
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class RecommendRequest {

    @JsonProperty("arxiv_id")
    private String arxivId;

    @JsonProperty("top_k")
    @Min(1)
    @Max(20)
    private int topK = 5;
}
