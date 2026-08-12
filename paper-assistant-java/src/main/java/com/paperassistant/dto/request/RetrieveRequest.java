package com.paperassistant.dto.request;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 向量检索请求（对应 Python {@code RetrieveRequest}）。
 *
 * <p>{@code top_k} 默认取 10，范围 [1, 50]（@Min/@Max）。
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class RetrieveRequest {

    @JsonProperty("query")
    private String query;

    @JsonProperty("top_k")
    @Min(1)
    @Max(50)
    private int topK = 10;
}
