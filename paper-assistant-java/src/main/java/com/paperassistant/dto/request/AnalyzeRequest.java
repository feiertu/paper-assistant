package com.paperassistant.dto.request;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 全局论文分析请求（对应 Python {@code AnalyzeRequest}）。
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class AnalyzeRequest {

    @JsonProperty("query")
    private String query = "";

    @JsonProperty("lang")
    private String lang = "zh";
}
