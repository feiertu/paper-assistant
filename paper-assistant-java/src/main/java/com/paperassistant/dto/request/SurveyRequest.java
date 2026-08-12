package com.paperassistant.dto.request;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 综述生成请求（对应 Python {@code SurveyRequest}）。
 *
 * <p>{@code top_k} 默认 10，范围 [1, 50]。
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class SurveyRequest {

    @JsonProperty("query")
    private String query;

    @JsonProperty("top_k")
    @Min(1)
    @Max(50)
    private int topK = 10;

    @JsonProperty("lang")
    private String lang = "zh";
}
