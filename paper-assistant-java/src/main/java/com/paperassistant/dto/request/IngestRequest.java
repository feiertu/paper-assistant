package com.paperassistant.dto.request;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 批量入库请求（对应 Python {@code IngestRequest}）。
 *
 * <p>{@code parsedDir} 留空时使用默认解析目录；{@code reset} 为 true 时先清空索引。
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class IngestRequest {

    @JsonProperty("reset")
    private boolean reset = false;

    @JsonProperty("parsed_dir")
    private String parsedDir = "";
}
