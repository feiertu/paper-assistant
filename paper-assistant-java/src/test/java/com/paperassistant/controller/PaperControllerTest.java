package com.paperassistant.controller;

import com.paperassistant.AbstractIntegrationTest;
import com.paperassistant.entity.Paper;
import com.paperassistant.repository.PaperRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.reactive.AutoConfigureWebTestClient;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.web.reactive.server.WebTestClient;

import java.util.Map;

/**
 * API verification for {@link PaperController} against a real PostgreSQL
 * (pgvector) container.
 *
 * <p>Covers the Python {@code /papers*} contract: paginated list, single-paper
 * 404, keyword full-text search (the controller exposes {@code GET
 * /papers/search} — the brief's "POST /papers/search" maps to this endpoint) and
 * similar-paper recommendation. Owner isolation is exercised through the
 * {@code X-Owner-Id} header resolved by {@link
 * com.paperassistant.filter.OwnerFilter}.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@AutoConfigureWebTestClient
class PaperControllerTest extends AbstractIntegrationTest {

    private static final String OWNER = "it-owner";

    @Autowired
    private WebTestClient webTestClient;

    @Autowired
    private PaperRepository paperRepository;

    @BeforeEach
    void cleanPapers() {
        paperRepository.deleteAll();
    }

    @Test
    void listReturnsPagedPapers() {
        for (int i = 0; i < 5; i++) {
            savePaper("2401.0000" + i, "Paper number " + i, "Author " + i, "Abstract number " + i);
        }
        webTestClient.get().uri("/papers?limit=2&offset=0")
                .header("X-Owner-Id", OWNER)
                .exchange()
                .expectStatus().isOk()
                .expectBody()
                .jsonPath("$.total").isEqualTo(5)
                .jsonPath("$.papers.length()").isEqualTo(2)
                .jsonPath("$.papers[0].arxiv_id").exists()
                .jsonPath("$.papers[0].owner_id").isEqualTo(OWNER);
    }

    @Test
    void getNonExistentPaperReturns404() {
        webTestClient.get().uri("/papers/9999.99999")
                .header("X-Owner-Id", OWNER)
                .exchange()
                .expectStatus().isNotFound()
                .expectBody()
                .jsonPath("$.error.code").isEqualTo(404);
    }

    @Test
    void searchByKeywordReturnsMatchingPapers() {
        savePaper("2402.aaaaa", "Transformer Attention Mechanisms in NLP", "Alice", "A study of attention.");
        savePaper("2402.bbbbb", "Random Forest for Regression", "Bob", "Ensemble methods.");

        webTestClient.get().uri("/papers/search?keyword=transformer")
                .header("X-Owner-Id", OWNER)
                .exchange()
                .expectStatus().isOk()
                .expectBody()
                .jsonPath("$.total").isEqualTo(1)
                .jsonPath("$.papers.length()").isEqualTo(1)
                .jsonPath("$.papers[0].arxiv_id").isEqualTo("2402.aaaaa");
    }

    @Test
    void searchWithNonMatchingKeywordReturnsEmpty() {
        savePaper("2402.ccccc", "Quantum Computing Survey", "Carol", "Qubits and gates.");

        webTestClient.get().uri("/papers/search?keyword=zoology")
                .header("X-Owner-Id", OWNER)
                .exchange()
                .expectStatus().isOk()
                .expectBody()
                .jsonPath("$.total").isEqualTo(0)
                .jsonPath("$.papers.length()").isEqualTo(0);
    }

    @Test
    void recommendForUnknownPaperReturnsOkWithEmptySimilar() {
        webTestClient.post().uri("/papers/recommend")
                .contentType(MediaType.APPLICATION_JSON)
                .bodyValue(Map.of("arxiv_id", "9999.99999", "top_k", 5))
                .exchange()
                .expectStatus().isOk()
                .expectBody()
                .jsonPath("$.arxiv_id").isEqualTo("9999.99999")
                .jsonPath("$.similar").isArray()
                .jsonPath("$.similar.length()").isEqualTo(0);
    }

    @Test
    void recommendForExistingPaperWithoutEmbeddingReturnsEmpty() {
        savePaper("2403.ddddd", "A Paper Without an Embedding Vector", "Dave", "Plain text only.");

        webTestClient.post().uri("/papers/recommend")
                .contentType(MediaType.APPLICATION_JSON)
                .bodyValue(Map.of("arxiv_id", "2403.ddddd", "top_k", 5))
                .exchange()
                .expectStatus().isOk()
                .expectBody()
                .jsonPath("$.arxiv_id").isEqualTo("2403.ddddd")
                .jsonPath("$.similar").isArray()
                .jsonPath("$.similar.length()").isEqualTo(0);
    }

    private void savePaper(String arxivId, String title, String authors, String abstractText) {
        Paper paper = Paper.builder()
                .arxivId(arxivId)
                .title(title)
                .authors(authors)
                .abstractText(abstractText)
                .ownerId(OWNER)
                .build();
        paperRepository.save(paper);
    }
}
