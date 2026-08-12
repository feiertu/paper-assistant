package com.paperassistant;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.reactive.AutoConfigureWebTestClient;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.web.reactive.server.WebTestClient;

/**
 * Full-context integration test: boots the whole application against a real
 * PostgreSQL (pgvector) container started by Testcontainers, lets Flyway
 * auto-migrate the schema, and verifies {@code ddl-auto: validate} passes
 * (including the pgvector {@code vector(1024)} column via {@link
 * com.paperassistant.entity.VectorType}).
 *
 * <p>If the Spring context fails to load (wrong column type, missing extension,
 * bean wiring error) every test in this class fails — the test methods themselves
 * are intentionally light.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@AutoConfigureWebTestClient
class PaperAssistantApplicationTests extends AbstractIntegrationTest {

    @Autowired
    private WebTestClient webTestClient;

    @Test
    void contextLoads() {
        // A loaded Spring context + healthy Hibernate/Flyway wiring is the assertion.
    }

    @Test
    void healthEndpointReturnsOk() {
        webTestClient.get().uri("/health")
                .exchange()
                .expectStatus().isOk()
                .expectBody()
                .jsonPath("$.status").isEqualTo("ok");
    }
}
