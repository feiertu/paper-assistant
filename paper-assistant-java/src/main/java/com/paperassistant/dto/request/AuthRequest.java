package com.paperassistant.dto.request;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 用户认证请求（对应 Python {@code AuthRequest}）。
 *
 * <p>{@code mode} 为 {@code "login"} 或 {@code "register"}；{@code confirm} 仅注册时使用。
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class AuthRequest {

    @JsonProperty("username")
    private String username;

    @JsonProperty("password")
    private String password;

    @JsonProperty("mode")
    private String mode = "login";

    @JsonProperty("confirm")
    private String confirm = "";
}
