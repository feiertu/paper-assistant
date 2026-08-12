package com.paperassistant.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.paperassistant.config.AppConfig;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.web.server.ResponseStatusException;

import java.lang.reflect.Constructor;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Unit tests for {@link AuthService} — no Spring context. Exercises the SHA-256
 * hashing, salt generation, validation rules, and the full login/register flow
 * against a {@code users.json} in an isolated temp directory.
 */
class AuthServiceTest {

    @TempDir
    Path tempDir;

    /** An {@link AppConfig} whose {@code dataDir} points at {@code dir}. */
    private static AppConfig config(String dataDir) {
        try {
            Constructor<?> ctor = AppConfig.class.getDeclaredConstructors()[0];
            Object[] args = new Object[AppConfig.class.getRecordComponents().length];
            args[0] = dataDir; // dataDir is the first record component
            return (AppConfig) ctor.newInstance(args);
        } catch (ReflectiveOperationException e) {
            throw new IllegalStateException("Could not build AppConfig", e);
        }
    }

    private AuthService service() {
        return new AuthService(config(tempDir.toString()), new ObjectMapper());
    }

    /** Independent SHA-256 hex of {@code input} for cross-checking. */
    private static String sha256(String input) throws Exception {
        MessageDigest md = MessageDigest.getInstance("SHA-256");
        byte[] digest = md.digest(input.getBytes(StandardCharsets.UTF_8));
        StringBuilder sb = new StringBuilder();
        for (byte b : digest) {
            sb.append(String.format("%02x", b));
        }
        return sb.toString();
    }

    // ---------- Hashing / salt ----------

    @Test
    void hashPasswordIsSha256OfPasswordPlusSalt() throws Exception {
        AuthService svc = service();
        Map<String, String> result = svc.hashPassword("secret123", "aabbccddeeff0011");
        assertEquals("aabbccddeeff0011", result.get("salt"));
        assertEquals(sha256("secret123" + "aabbccddeeff0011"), result.get("hash"));
        assertEquals(64, result.get("hash").length());
    }

    @Test
    void hashPasswordGeneratesSaltWhenNull() {
        AuthService svc = service();
        Map<String, String> r1 = svc.hashPassword("secret123", null);
        Map<String, String> r2 = svc.hashPassword("secret123", null);
        assertNotNull(r1.get("salt"));
        assertEquals(16, r1.get("salt").length());
        // 随机 salt → 相同密码得到不同哈希
        assertNotEquals(r1.get("salt"), r2.get("salt"));
        assertNotEquals(r1.get("hash"), r2.get("hash"));
    }

    @Test
    void generateSaltReturns16HexChars() {
        AuthService svc = service();
        String salt = svc.generateSalt();
        assertEquals(16, salt.length());
        assertTrue(salt.matches("[0-9a-f]{16}"));
    }

    // ---------- Validation ----------

    @Test
    void validateUsernameAcceptsValidNames() {
        AuthService svc = service();
        assertTrue(svc.validateUsername("alice"));
        assertTrue(svc.validateUsername("Alice_123"));
        assertTrue(svc.validateUsername("abc"));
    }

    @Test
    void validateUsernameRejectsInvalidNames() {
        AuthService svc = service();
        assertFalse(svc.validateUsername("ab"));                 // too short
        assertFalse(svc.validateUsername("a".repeat(21)));       // too long
        assertFalse(svc.validateUsername("a b"));                // space
        assertFalse(svc.validateUsername("abc!"));
        assertFalse(svc.validateUsername(""));
        assertFalse(svc.validateUsername(null));
    }

    @Test
    void validatePasswordAcceptsValidPasswords() {
        AuthService svc = service();
        assertTrue(svc.validatePassword("abc12345"));            // letter + digit, 8 chars
        assertTrue(svc.validatePassword("A1bcdefg"));
        assertTrue(svc.validatePassword("correct-horse-battery9"));
    }

    @Test
    void validatePasswordRejectsInvalidPasswords() {
        AuthService svc = service();
        assertFalse(svc.validatePassword("short1"));             // 7 chars
        assertFalse(svc.validatePassword("abcdefgh"));           // no digit
        assertFalse(svc.validatePassword("12345678"));           // no letter
        assertFalse(svc.validatePassword("abc123中"));            // CJK
        assertFalse(svc.validatePassword(""));
        assertFalse(svc.validatePassword(null));
    }

    // ---------- First launch / login ----------

    @Test
    void firstLaunchCreatesDemoAccountAndPersistsFile() {
        AuthService svc = service();
        Map<String, Object> result = svc.login("demo", "demo123");
        assertEquals("ok", result.get("status"));
        assertEquals("demo", result.get("username"));

        Path file = tempDir.resolve("users.json");
        assertTrue(Files.isRegularFile(file));
    }

    @Test
    void loginSucceedsForStoredUser() {
        AuthService svc = service();
        svc.register("alice", "password9", "password9");
        Map<String, Object> result = svc.login("alice", "password9");
        assertEquals("ok", result.get("status"));
        assertEquals("alice", result.get("username"));
    }

    @Test
    void loginTrimsUsername() {
        AuthService svc = service();
        svc.register("bob", "password9", "password9");
        assertEquals("ok", svc.login("  bob  ", "password9").get("status"));
    }

    @Test
    void loginRejectsWrongPassword() {
        AuthService svc = service();
        ResponseStatusException ex = assertThrows(ResponseStatusException.class,
                () -> svc.login("demo", "wrong-pass1"));
        assertEquals(401, ex.getStatusCode().value());
        assertEquals("用户名或密码错误", ex.getReason());
    }

    @Test
    void loginRejectsUnknownUser() {
        AuthService svc = service();
        assertThrows(ResponseStatusException.class, () -> svc.login("ghost", "password9"));
    }

    // ---------- Register ----------

    @Test
    void registerPersistsUserAndHashIsVerifiable() throws Exception {
        AuthService svc = service();
        svc.register("carol", "summer2026", "summer2026");

        Map<String, Object> users = new ObjectMapper().readValue(
                tempDir.resolve("users.json").toFile(),
                new com.fasterxml.jackson.core.type.TypeReference<Map<String, Object>>() {});
        @SuppressWarnings("unchecked")
        Map<String, Object> entry = (Map<String, Object>) users.get("carol");
        assertNotNull(entry);
        String salt = String.valueOf(entry.get("salt"));
        String hash = String.valueOf(entry.get("hash"));
        assertEquals(sha256("summer2026" + salt), hash);
        assertTrue(String.valueOf(entry.get("created_at")).matches("\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2}"));
    }

    @Test
    void registerRejectsDuplicateUsername() {
        AuthService svc = service();
        svc.register("dave", "password9", "password9");
        ResponseStatusException ex = assertThrows(ResponseStatusException.class,
                () -> svc.register("dave", "another9", "another9"));
        assertEquals(409, ex.getStatusCode().value());
        assertEquals("用户名已存在", ex.getReason());
    }

    @Test
    void registerRejectsInvalidUsername() {
        AuthService svc = service();
        ResponseStatusException ex = assertThrows(ResponseStatusException.class,
                () -> svc.register("ab", "password9", "password9"));
        assertEquals(400, ex.getStatusCode().value());
    }

    @Test
    void registerRejectsWeakPasswords() {
        AuthService svc = service();
        // too short
        assertEquals(400, assertThrows(ResponseStatusException.class,
                () -> svc.register("eve", "pass1", "pass1")).getStatusCode().value());
        // no digit
        assertEquals(400, assertThrows(ResponseStatusException.class,
                () -> svc.register("eve", "password", "password")).getStatusCode().value());
        // no letter
        assertEquals(400, assertThrows(ResponseStatusException.class,
                () -> svc.register("eve", "12345678", "12345678")).getStatusCode().value());
        // CJK（长度足够、含字母数字，仅因含汉字被拒）
        assertEquals(400, assertThrows(ResponseStatusException.class,
                () -> svc.register("eve", "abc12345密", "abc12345密")).getStatusCode().value());
        // confirm mismatch
        assertEquals(400, assertThrows(ResponseStatusException.class,
                () -> svc.register("eve", "password9", "password8")).getStatusCode().value());
        // 失败的注册不应落盘
        assertFalse(Files.isRegularFile(tempDir.resolve("users.json")));
    }
}
