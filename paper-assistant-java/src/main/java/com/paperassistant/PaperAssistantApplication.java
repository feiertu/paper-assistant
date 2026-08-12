package com.paperassistant;

import com.paperassistant.config.AppConfig;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.cache.annotation.EnableCaching;

/**
 * Paper Assistant backend — Java Spring Boot rewrite of the Python FastAPI
 * service. Reactive (WebFlux), with Caffeine caching and typed configuration
 * backed by {@link AppConfig}.
 */
@SpringBootApplication
@EnableConfigurationProperties(AppConfig.class)
@EnableCaching
public class PaperAssistantApplication {

    public static void main(String[] args) {
        SpringApplication.run(PaperAssistantApplication.class, args);
    }
}
