package com.paperassistant.dto.request;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * RAG 问答请求（对应 Python {@code RAGQueryRequest}）。
 *
 * <p>{@code top_k} 默认 10，范围 [1, 50]；{@code temperature} 可为空
 * （不传时由服务端使用默认采样温度）。
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class RAGQueryRequest {

    @JsonProperty("query")
    private String query;

    @JsonProperty("top_k")
    @Min(1)
    @Max(50)
    private int topK = 10;

    @JsonProperty("lang")
    private String lang = "zh";

    @JsonProperty("temperature")
    private Double temperature;
}
