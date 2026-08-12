package com.paperassistant.dto.request;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.Map;

/**
 * 文本直注入库请求（对应 Python {@code IngestTextRequest}）。
 *
 * <p>{@code metadata} 可选，透传给入库记录。
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class IngestTextRequest {

    @JsonProperty("text")
    private String text;

    @JsonProperty("metadata")
    private Map<String, Object> metadata;
}
