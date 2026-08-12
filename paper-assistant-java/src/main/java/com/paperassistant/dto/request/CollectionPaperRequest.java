package com.paperassistant.dto.request;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 向集合添加论文请求（对应 Python {@code CollectionPaperRequest}）。
 *
 * <p>论文主键 {@code paper_id} 在 {@code POST /collections/{id}/papers} 中透传。
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class CollectionPaperRequest {

    @JsonProperty("paper_id")
    private int paperId;
}
