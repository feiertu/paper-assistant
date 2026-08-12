package com.paperassistant.filter;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.annotation.Order;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.web.server.ServerWebExchange;
import org.springframework.web.server.WebFilter;
import org.springframework.web.server.WebFilterChain;
import reactor.core.publisher.Mono;

/**
 * Logs {@code method + path → status + duration_ms} at INFO level for every
 * request, mirroring the Python {@code request_log_middleware} in
 * {@code src/api/main.py}. Runs outermost so it wraps the entire filter chain
 * and captures the final response status right before the response commits.
 */
@Order(1)
public class RequestLogFilter implements WebFilter {

    private static final Logger log = LoggerFactory.getLogger(RequestLogFilter.class);

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, WebFilterChain chain) {
        ServerHttpRequest request = exchange.getRequest();
        long start = System.currentTimeMillis();

        // Status is only reliable once the response is about to be committed.
        exchange.getResponse().beforeCommit(() -> {
            long durationMs = System.currentTimeMillis() - start;
            HttpStatusCode status = exchange.getResponse().getStatusCode();
            int statusCode = status != null ? status.value() : 0;
            log.info("{} {} → {} ({}ms)",
                    request.getMethod(), request.getPath(), statusCode, durationMs);
            return Mono.empty();
        });

        return chain.filter(exchange);
    }
}
