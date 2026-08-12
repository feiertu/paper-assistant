package com.paperassistant.filter;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.paperassistant.config.AppConfig;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.annotation.Order;
import org.springframework.core.io.buffer.DataBuffer;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.http.server.reactive.ServerHttpResponse;
import org.springframework.web.server.ServerWebExchange;
import org.springframework.web.server.WebFilter;
import org.springframework.web.server.WebFilterChain;
import reactor.core.publisher.Mono;

import java.util.Map;
import java.util.Set;

/**
 * Simple API-key authentication, mirroring the Python {@code ApiKeyMiddleware}.
 *
 * <p>Only active when {@link AppConfig#apiAuthEnabled()} is {@code true}.
 * Whitelisted paths and {@code OPTIONS} preflight requests always pass. When
 * auth is enabled but the key is null or blank the filter fails closed with a
 * 500 (misconfiguration), and a missing / mismatched {@code X-API-Key} header
 * yields a 401.
 */
@Order(3)
public class ApiKeyFilter implements WebFilter {

    private static final Logger log = LoggerFactory.getLogger(ApiKeyFilter.class);

    private static final Set<String> WHITELIST = Set.of(
            "/health", "/config", "/api/docs", "/api/redoc", "/api/openapi.json");

    private final AppConfig config;
    private final ObjectMapper objectMapper = new ObjectMapper();

    public ApiKeyFilter(AppConfig config) {
        this.config = config;
    }

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, WebFilterChain chain) {
        ServerHttpRequest request = exchange.getRequest();
        String path = request.getPath().value();

        // Whitelist paths and CORS preflight always pass.
        if (WHITELIST.contains(path) || HttpMethod.OPTIONS.equals(request.getMethod())) {
            return chain.filter(exchange);
        }

        // Filter is only active when auth is enabled.
        if (!config.apiAuthEnabled()) {
            return chain.filter(exchange);
        }

        // Auth enabled but the key is null/blank: fail closed (misconfiguration).
        if (config.apiAuthKey() == null || config.apiAuthKey().isBlank()) {
            log.error("API auth enabled but API key is null/blank; rejecting all requests");
            return writeJson(exchange, HttpStatus.INTERNAL_SERVER_ERROR,
                    Map.of("detail", "服务器配置错误：API 鉴权密钥未设置"));
        }

        // Validate the X-API-Key header against the configured key.
        String clientKey = request.getHeaders().getFirst("X-API-Key");
        if (!config.apiAuthKey().equals(clientKey)) {
            log.warn("API key auth failed: path={}", path);
            return writeJson(exchange, HttpStatus.UNAUTHORIZED,
                    Map.of("detail", "未授权：请提供有效的 X-API-Key"));
        }

        return chain.filter(exchange);
    }

    private Mono<Void> writeJson(ServerWebExchange exchange, HttpStatus status, Map<String, ?> body) {
        byte[] bytes;
        try {
            bytes = objectMapper.writeValueAsBytes(body);
        } catch (JsonProcessingException e) {
            log.error("Failed to serialize error response", e);
            bytes = new byte[0];
        }
        ServerHttpResponse response = exchange.getResponse();
        response.setStatusCode(status);
        response.getHeaders().setContentType(MediaType.APPLICATION_JSON);
        DataBuffer buffer = response.bufferFactory().wrap(bytes);
        return response.writeWith(Mono.just(buffer));
    }
}
