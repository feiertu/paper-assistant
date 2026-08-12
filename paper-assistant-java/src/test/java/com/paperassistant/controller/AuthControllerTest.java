package com.paperassistant.controller;

import com.paperassistant.AbstractIntegrationTest;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.reactive.AutoConfigureWebTestClient;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.web.reactive.server.WebTestClient;

import java.util.Map;

/**
 * API verification for {@link AuthController} against a real PostgreSQL
 * (pgvector) container.
 *
 * <p>Covers the Python {@code /auth/*} contract: login with the first-launch
 * {@code demo/demo123} account (200), wrong password (401), register with valid
 * input (200), register with invalid input (400) and duplicate username (409).
 * Error responses use the unified {@code {"error": {"code", "message"}}}
 * envelope produced by {@link com.paperassistant.config.GlobalExceptionHandler}.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@AutoConfigureWebTestClient
class AuthControllerTest extends AbstractIntegrationTest {

    @Autowired
    private WebTestClient webTestClient;

    @Test
    void loginWithDemoCredentialsReturns200() {
        webTestClient.post().uri("/auth/login")
                .contentType(MediaType.APPLICATION_JSON)
                .bodyValue(Map.of("username", "demo", "password", "demo123"))
                .exchange()
                .expectStatus().isOk()
                .expectBody()
                .jsonPath("$.status").isEqualTo("ok")
                .jsonPath("$.username").isEqualTo("demo");
    }

    @Test
    void loginWithWrongPasswordReturns401() {
        webTestClient.post().uri("/auth/login")
                .contentType(MediaType.APPLICATION_JSON)
                .bodyValue(Map.of("username", "demo", "password", "wrong-pass1"))
                .exchange()
                .expectStatus().isUnauthorized()
                .expectBody()
                .jsonPath("$.error.code").isEqualTo(401);
    }

    @Test
    void registerWithValidInputReturns200() {
        String username = uniqueUsername("ituser");
        webTestClient.post().uri("/auth/register")
                .contentType(MediaType.APPLICATION_JSON)
                .bodyValue(Map.of("username", username, "password", "password9", "confirm", "password9"))
                .exchange()
                .expectStatus().isOk()
                .expectBody()
                .jsonPath("$.status").isEqualTo("ok")
                .jsonPath("$.username").isEqualTo(username);
    }

    @Test
    void registerWithInvalidInputReturns400() {
        // Username too short ("ab") — validation fails with 400.
        webTestClient.post().uri("/auth/register")
                .contentType(MediaType.APPLICATION_JSON)
                .bodyValue(Map.of("username", "ab", "password", "password9", "confirm", "password9"))
                .exchange()
                .expectStatus().isBadRequest()
                .expectBody()
                .jsonPath("$.error.code").isEqualTo(400);
    }

    @Test
    void registerDuplicateUsernameReturns409() {
        String username = uniqueUsername("dupuser");
        Map<String, Object> body = Map.of(
                "username", username, "password", "password9", "confirm", "password9");

        webTestClient.post().uri("/auth/register")
                .contentType(MediaType.APPLICATION_JSON)
                .bodyValue(body)
                .exchange()
                .expectStatus().isOk();

        webTestClient.post().uri("/auth/register")
                .contentType(MediaType.APPLICATION_JSON)
                .bodyValue(body)
                .exchange()
                .expectStatus().isEqualTo(409)
                .expectBody()
                .jsonPath("$.error.code").isEqualTo(409);
    }

    /** Unique 3-20 char {@code [a-zA-Z0-9_]} username for test isolation. */
    private static String uniqueUsername(String prefix) {
        return prefix + "_" + Long.toHexString(System.nanoTime() % 1_000_000L);
    }
}
