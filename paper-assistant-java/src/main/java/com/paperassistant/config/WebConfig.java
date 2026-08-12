package com.paperassistant.config;

import com.paperassistant.filter.ApiKeyFilter;
import com.paperassistant.filter.OwnerFilter;
import com.paperassistant.filter.RateLimitFilter;
import com.paperassistant.filter.RequestLogFilter;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.annotation.Order;
import org.springframework.web.cors.CorsConfiguration;
import org.springframework.web.cors.reactive.CorsWebFilter;
import org.springframework.web.cors.reactive.UrlBasedCorsConfigurationSource;
import org.springframework.web.reactive.config.CorsRegistration;
import org.springframework.web.reactive.config.CorsRegistry;
import org.springframework.web.reactive.config.WebFluxConfigurer;
import org.springframework.web.server.WebFilter;

import java.util.Arrays;
import java.util.List;

/**
 * Web-layer configuration: registers the WebFilter chain that replicates the
 * Python middleware, and configures CORS from
 * {@link AppConfig#apiCorsOrigins()}.
 *
 * <p>Filter ordering (outermost → innermost, driven by the class-level
 * {@code @Order} annotations) is {@link CorsWebFilter} (@Order(0), wraps the
 * whole chain so filter-level 401/429 responses get CORS headers) → {@link
 * RequestLogFilter} → {@link RateLimitFilter} → {@link ApiKeyFilter} → {@link
 * OwnerFilter}. The innermost {@link OwnerFilter} is the one that sets the
 * {@code owner_id} attribute controllers read.
 *
 * <p>CORS origins come from {@link AppConfig#apiCorsOrigins()}. A blank value
 * denies all cross-origin access (matching the Python CORSMiddleware), so
 * allow-credentials is only enabled for explicitly configured origins.
 */
@Configuration
public class WebConfig implements WebFluxConfigurer {

    private final AppConfig appConfig;

    public WebConfig(AppConfig appConfig) {
        this.appConfig = appConfig;
    }

    /**
     * Filter-level CORS handling so short-circuit responses written by other
     * filters (401/429) still carry the {@code Access-Control-Allow-Origin}
     * header. Runs outermost; the handler-level {@code addCorsMappings} below
     * remains for handler responses and the two do not conflict.
     */
    @Bean
    @Order(0)
    public CorsWebFilter corsWebFilter() {
        CorsConfiguration config = new CorsConfiguration();
        List<String> origins = parseOrigins(appConfig.apiCorsOrigins());
        if (origins.isEmpty()) {
            // Blank origins → deny all cross-origin (matches Python CORSMiddleware).
            config.setAllowedOrigins(List.of());
            config.setAllowCredentials(false);
        } else {
            config.setAllowedOrigins(origins);
            config.setAllowCredentials(true);
        }
        config.setAllowedMethods(List.of("GET", "POST", "DELETE", "OPTIONS"));
        config.setAllowedHeaders(List.of("*"));
        UrlBasedCorsConfigurationSource source = new UrlBasedCorsConfigurationSource();
        source.registerCorsConfiguration("/**", config);
        return new CorsWebFilter(source);
    }

    @Bean
    public WebFilter requestLogFilter() {
        return new RequestLogFilter();
    }

    @Bean
    public WebFilter rateLimitFilter() {
        return new RateLimitFilter(appConfig);
    }

    @Bean
    public WebFilter apiKeyFilter() {
        return new ApiKeyFilter(appConfig);
    }

    @Bean
    public WebFilter ownerFilter() {
        return new OwnerFilter(appConfig);
    }

    @Override
    public void addCorsMappings(CorsRegistry registry) {
        List<String> origins = parseOrigins(appConfig.apiCorsOrigins());
        CorsRegistration registration = registry.addMapping("/**")
                .allowedMethods("GET", "POST", "DELETE", "OPTIONS")
                .allowedHeaders("*");
        if (origins.isEmpty()) {
            // Blank origins → deny all cross-origin (matches Python CORSMiddleware).
            registration.allowedOrigins(new String[0]).allowCredentials(false);
        } else {
            registration.allowedOrigins(origins.toArray(new String[0])).allowCredentials(true);
        }
    }

    /** Splits a comma-separated origin list, trimming and dropping blanks. */
    private static List<String> parseOrigins(String csv) {
        if (csv == null || csv.isBlank()) {
            return List.of();
        }
        return Arrays.stream(csv.split(","))
                .map(String::trim)
                .filter(s -> !s.isEmpty())
                .toList();
    }
}
