package com.paperassistant.filter;

import com.paperassistant.config.AppConfig;
import org.springframework.core.annotation.Order;
import org.springframework.http.HttpCookie;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.web.server.ServerWebExchange;
import org.springframework.web.server.WebFilter;
import org.springframework.web.server.WebFilterChain;
import reactor.core.publisher.Mono;

import java.util.List;
import java.util.Set;

/**
 * Multi-user isolation filter, mirroring the Python {@code OwnerMiddleware}.
 *
 * <p>Resolves the owner id from the session cookie (name from
 * {@link AppConfig#sessionCookie()}, default {@code paper_session}) falling back
 * to the {@code X-Owner-Id} header (used by Streamlit internal calls), and
 * stores it in {@code exchange.getAttributes()["owner_id"]} for controllers to
 * read. Whitelisted endpoints always get an empty owner id.
 */
@Order(4)
public class OwnerFilter implements WebFilter {

    /** Attribute key under which the resolved owner id is exposed to controllers. */
    public static final String OWNER_ID_ATTR = "owner_id";

    private static final Set<String> WHITELIST = Set.of(
            "/health", "/api/docs", "/api/redoc", "/api/openapi.json");

    private final String sessionCookieName;

    public OwnerFilter(AppConfig config) {
        this.sessionCookieName = config.sessionCookie();
    }

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, WebFilterChain chain) {
        exchange.getAttributes().put(OWNER_ID_ATTR, resolveOwnerId(exchange));
        return chain.filter(exchange);
    }

    private String resolveOwnerId(ServerWebExchange exchange) {
        ServerHttpRequest request = exchange.getRequest();

        // Whitelisted endpoints always get an empty owner.
        if (WHITELIST.contains(request.getPath().value())) {
            return "";
        }

        // Priority: session cookie, then X-Owner-Id header.
        String ownerId = "";
        List<HttpCookie> cookies = request.getCookies().get(sessionCookieName);
        if (cookies != null && !cookies.isEmpty()) {
            String cookieValue = cookies.get(0).getValue();
            if (cookieValue != null && !cookieValue.isBlank()) {
                ownerId = cookieValue;
            }
        }
        if (ownerId.isEmpty()) {
            String headerValue = request.getHeaders().getFirst("X-Owner-Id");
            if (headerValue != null) {
                ownerId = headerValue;
            }
        }
        return ownerId;
    }

    /**
     * Reads the owner id this filter resolved for the exchange, or {@code ""}
     * when the filter has not run / the id is absent.
     */
    public static String getOwnerId(ServerWebExchange exchange) {
        Object value = exchange.getAttributes().get(OWNER_ID_ATTR);
        return value instanceof String s ? s : "";
    }
}
