package com.paperassistant.dto.request;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 创建论文集合请求（对应 Python {@code CreateCollectionRequest}）。
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class CreateCollectionRequest {

    @JsonProperty("name")
    private String name;

    @JsonProperty("description")
    private String description = "";
}
