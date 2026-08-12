package com.paperassistant.filter;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.paperassistant.config.AppConfig;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.annotation.Order;
import org.springframework.core.io.buffer.DataBuffer;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.http.server.reactive.ServerHttpResponse;
import org.springframework.web.server.ServerWebExchange;
import org.springframework.web.server.WebFilter;
import org.springframework.web.server.WebFilterChain;
import reactor.core.publisher.Mono;

import java.net.InetSocketAddress;
import java.util.Deque;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentLinkedDeque;

/**
 * Sliding-window global rate limiter keyed by the real client IP, mirroring the
 * Python {@code RateLimitMiddleware}. The limit comes from
 * {@link AppConfig#apiRateLimit()} (e.g. {@code "30/minute"}) and is enforced
 * per IP with a {@code ConcurrentHashMap<String, Deque<Long>>} that evicts
 * expired timestamps on every check.
 */
@Order(2)
public class RateLimitFilter implements WebFilter {

    private static final Logger log = LoggerFactory.getLogger(RateLimitFilter.class);

    private static final Set<String> WHITELIST = Set.of(
            "/health", "/config", "/api/docs", "/api/redoc", "/api/openapi.json");

    private final int maxRequests;
    private final int windowSeconds;
    private final ConcurrentHashMap<String, Deque<Long>> clients = new ConcurrentHashMap<>();
    private final ObjectMapper objectMapper = new ObjectMapper();

    public RateLimitFilter(AppConfig config) {
        int[] parsed = parseRateLimit(config.apiRateLimit());
        this.maxRequests = parsed[0];
        this.windowSeconds = parsed[1];
    }

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, WebFilterChain chain) {
        String path = exchange.getRequest().getPath().value();

        if (WHITELIST.contains(path)) {
            return chain.filter(exchange);
        }

        String clientIp = getRealIp(exchange);
        long now = System.currentTimeMillis();
        long windowStart = now - windowSeconds * 1000L;

        Deque<Long> deque = clients.computeIfAbsent(clientIp, k -> new ConcurrentLinkedDeque<>());

        // Evict timestamps that fell out of the sliding window.
        while (true) {
            Long oldest = deque.peekFirst();
            if (oldest == null || oldest > windowStart) {
                break;
            }
            deque.pollFirst();
        }

        if (deque.size() >= maxRequests) {
            log.warn("Rate limit hit: ip={} path={} count={}", clientIp, path, deque.size());
            return writeJson(exchange, HttpStatus.TOO_MANY_REQUESTS,
                    Map.of(
                            "detail", "请求过于频繁，限制 " + maxRequests + " 次/" + windowSeconds + "s",
                            "retry_after", windowSeconds));
        }

        deque.addLast(now);
        return chain.filter(exchange);
    }

    /**
     * Real client IP: {@code X-Forwarded-For} (first value) &gt; {@code X-Real-IP}
     * &gt; remote address. Falls back to {@code "unknown"}.
     */
    private static String getRealIp(ServerWebExchange exchange) {
        ServerHttpRequest request = exchange.getRequest();

        // X-Forwarded-For: "client, proxy1, proxy2" — take the first (original client).
        String xff = request.getHeaders().getFirst("X-Forwarded-For");
        if (xff != null && !xff.isBlank()) {
            return xff.split(",")[0].trim();
        }

        // X-Real-IP: single IP set by nginx.
        String xri = request.getHeaders().getFirst("X-Real-IP");
        if (xri != null && !xri.isBlank()) {
            return xri.trim();
        }

        // Direct connection (local dev, health checks).
        InetSocketAddress remote = request.getRemoteAddress();
        if (remote != null && remote.getAddress() != null) {
            return remote.getAddress().getHostAddress();
        }
        return "unknown";
    }

    /**
     * Parses a rate-limit string like {@code "30/minute"} into {@code {count, seconds}}.
     * "30/minute" → {30, 60}, "100/hour" → {100, 3600}, "5/second" → {5, 1}.
     * Falls back to {30, 60} on any parse failure, matching the Python behavior.
     */
    private static int[] parseRateLimit(String limitStr) {
        if (limitStr == null) {
            return new int[]{30, 60};
        }
        String[] parts = limitStr.trim().split("/");
        if (parts.length != 2) {
            return new int[]{30, 60};
        }
        int count;
        try {
            count = Integer.parseInt(parts[0].trim());
        } catch (NumberFormatException e) {
            count = 30;
        }
        String unit = parts[1].trim().toLowerCase();
        if (unit.endsWith("s")) {
            unit = unit.substring(0, unit.length() - 1);
        }
        int seconds = switch (unit) {
            case "second" -> 1;
            case "minute" -> 60;
            case "hour" -> 3600;
            case "day" -> 86400;
            default -> 60;
        };
        return new int[]{count, seconds};
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
