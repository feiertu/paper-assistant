package com.paperassistant.dto.request;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 单篇论文摘要请求（对应 Python {@code SummarizeRequest}）。
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class SummarizeRequest {

    @JsonProperty("arxiv_id")
    private String arxivId;

    @JsonProperty("lang")
    private String lang = "zh";
}
