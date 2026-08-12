package com.paperassistant;

import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.containers.PostgreSQLContainer;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Comparator;

/**
 * Shared base for all Testcontainers-backed integration tests.
 *
 * <p>Starts a single {@code pgvector/pgvector:pg16} PostgreSQL container once per
 * test JVM using the Testcontainers "singleton container" pattern (see the docs
 * on sharing containers between test classes): the container is started in a
 * static initializer and is never stopped by the per-class JUnit lifecycle
 * (Ryuk cleans it up when the JVM exits).
 *
 * <p>This matters for Spring's context cache: the JDBC URL for the DataSource is
 * captured by {@link DynamicPropertySource} the first time a test context boots,
 * and the same cached context is reused by every class. If the container were
 * managed by {@code @Container}, JUnit would stop it after each class and restart
 * it on a new port for the next one, leaving the cached DataSource pointing at a
 * dead port — every later DB access fails with "Connection refused".
 *
 * <p>Points {@code spring.datasource.*} at the container so Flyway auto-migrates
 * the schema and {@code ddl-auto: validate} runs against a real database.
 * Subclasses should be {@code @SpringBootTest(webEnvironment = RANDOM_PORT)} +
 * {@code @AutoConfigureWebTestClient} so the full Netty stack and WebFilter chain
 * are exercised.
 *
 * <p>Test-only overrides: a throw-away {@code target/test-data-it} data dir
 * (AuthService's {@code users.json} must not pollute the real {@code data/}
 * folder), a high rate limit so the sliding-window filter never trips, and blank
 * provider keys so no real OpenAI/Voyage calls are attempted.
 *
 * <p><b>Requires Docker:</b> the container is started eagerly, so these tests
 * fail (rather than silently skip) when Docker is unavailable.
 */
public abstract class AbstractIntegrationTest {

    /** Shared PostgreSQL (pgvector) container for the whole test JVM. */
    private static final PostgreSQLContainer<?> POSTGRES =
            new PostgreSQLContainer<>("pgvector/pgvector:pg16")
                    .withDatabaseName("paper_assistant")
                    .withUsername("paper_assistant")
                    .withPassword("paper_assistant");

    static {
        // Singleton container: started once, never stopped by JUnit (see class javadoc).
        POSTGRES.start();

        // Remove stale users.json / parsed data from a previous run.
        Path dir = Path.of("target/test-data-it");
        if (Files.exists(dir)) {
            try (var stream = Files.walk(dir)) {
                stream.sorted(Comparator.reverseOrder()).forEach(p -> {
                    try {
                        Files.deleteIfExists(p);
                    } catch (IOException ignored) {
                        // best-effort cleanup
                    }
                });
            } catch (IOException ignored) {
                // best-effort cleanup
            }
        }
    }

    @DynamicPropertySource
    static void testProperties(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", POSTGRES::getJdbcUrl);
        registry.add("spring.datasource.username", POSTGRES::getUsername);
        registry.add("spring.datasource.password", POSTGRES::getPassword);
        registry.add("spring.datasource.driver-class-name", () -> "org.postgresql.Driver");
        // Isolate user/parsed data from the real workspace.
        registry.add("paper-assistant.data-dir", () -> "target/test-data-it");
        // Keep the rate limiter from ever tripping during the test run.
        registry.add("paper-assistant.api-rate-limit", () -> "100000/minute");
        // Never hit real LLM/embedding providers from tests. spring-ai 1.0.0-M6
        // refuses to create its OpenAI beans when the key is blank (it throws
        // "OpenAI API key must be set"), so a dummy key is supplied to let the
        // inert beans construct; no request is ever issued because the tests
        // under /auth and /papers do not call any LLM-backed endpoint.
        registry.add("paper-assistant.openai-api-key", () -> "");
        registry.add("paper-assistant.embedding-api-key", () -> "");
        registry.add("paper-assistant.voyage-api-key", () -> "");
        registry.add("spring.ai.openai.api-key", () -> "test-only-key");
    }
}
