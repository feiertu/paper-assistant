package com.paperassistant.service;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.paperassistant.config.AppConfig;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.regex.Pattern;

/**
 * 用户认证服务 — Python {@code src/api/main.py} 用户认证辅助的 Java 移植。
 *
 * <p>用户存储于 {@code config.dataDir()/users.json}（与 Python 版同格式：
 * {@code {"username": {"hash": ..., "salt": ..., "created_at": ...}}}）。
 * 首次启动（或文件损坏/缺失）时自动创建 {@code demo/demo123} 账号。
 *
 * <p>密码哈希：SHA-256(password + 16 位十六进制 salt)；salt 生成：
 * SHA-256(nanoTime).hex()[:16]（与 Python {@code _hash_pw()} 一致）。
 *
 * <p>校验规则（与 Python 一致）：用户名 3-20 位 {@code [a-zA-Z0-9_]}；
 * 密码 ≥8 字符、必须包含英文字母与数字、不得含中日韩字符。
 * 失败通过抛出 {@link ResponseStatusException} 表达（{@code login}→401，
 * {@code register} 校验→400，重名→409），由全局异常处理器转换为统一错误信封。
 */
@Service
public class AuthService {

    private static final Logger log = LoggerFactory.getLogger(AuthService.class);

    /** 用户名规则（Python {@code _USERNAME_RE}）。 */
    private static final Pattern USERNAME_RE = Pattern.compile("^[a-zA-Z0-9_]{3,20}$");

    /** 密码必须包含字母（Python {@code re.search(r"[a-zA-Z]", pw)}）。 */
    private static final Pattern PASSWORD_LETTER_RE = Pattern.compile("[a-zA-Z]");

    /** 密码必须包含数字。 */
    private static final Pattern PASSWORD_DIGIT_RE = Pattern.compile("\\d");

    /**
     * CJK 字符范围（Python {@code _CJK_RE}，用 Unicode 转义以避免源文件编码问题）：
     * 一-鿿 U+4E00-U+9FFF、㐀-䶿 U+3400-U+4DBF、぀-ゟ U+3040-U+309F（平假名）、
     * ゠-ヿ U+30A0-U+30FF（片假名）、가-힯 U+AC00-U+D7AF（谚文音节）。
     */
    private static final Pattern CJK_RE = Pattern.compile(
            "[\\u4E00-\\u9FFF\\u3400-\\u4DBF\\u3040-\\u309F\\u30A0-\\u30FF\\uAC00-\\uD7AF]");

    /** {@code created_at} 时间格式（Python {@code time.strftime("%Y-%m-%d %H:%M:%S")}）。 */
    private static final DateTimeFormatter CREATED_AT_FORMAT =
            DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

    /** 首次启动默认账号。 */
    private static final String DEMO_USERNAME = "demo";
    private static final String DEMO_PASSWORD = "demo123";

    private final AppConfig appConfig;
    private final ObjectMapper objectMapper;

    public AuthService(AppConfig appConfig, ObjectMapper objectMapper) {
        this.appConfig = appConfig;
        this.objectMapper = objectMapper;
    }

    // ---------------------------------------------------------------------
    // 公开认证方法
    // ---------------------------------------------------------------------

    /**
     * 登录：校验用户名密码（Python {@code auth_login()}）。
     *
     * @return {@code {"status": "ok", "username": "..."}}
     * @throws ResponseStatusException 401 用户名或密码错误
     */
    public Map<String, Object> login(String username, String password) {
        String uname = strip(username);
        Map<String, Object> users = loadUsers();
        Object entryObj = users.get(uname);
        if (entryObj instanceof Map<?, ?> entry) {
            String salt = str(entry.get("salt"));
            String expectedHash = str(entry.get("hash"));
            // Python: h, _ = _hash_pw(password, salt); h == entry.hash
            if (!expectedHash.isEmpty() && sha256Hex(str(password) + salt).equals(expectedHash)) {
                return ok(uname);
            }
        }
        throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "用户名或密码错误");
    }

    /**
     * 注册：校验 + 哈希 + 写入 users.json（Python {@code auth_register()}）。
     *
     * @return {@code {"status": "ok", "username": "..."}}
     * @throws ResponseStatusException 400 校验失败 / 409 用户名已存在
     */
    public Map<String, Object> register(String username, String password, String confirm) {
        String uname = strip(username);
        if (!validateUsername(uname)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "用户名需 3-20 位，只能包含英文字母、数字和下划线");
        }
        String pw = str(password);
        if (pw.length() < 8) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "密码至少需要 8 个字符");
        }
        if (!PASSWORD_LETTER_RE.matcher(pw).find()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "密码必须包含至少一个英文字母");
        }
        if (!PASSWORD_DIGIT_RE.matcher(pw).find()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "密码必须包含至少一个数字");
        }
        if (CJK_RE.matcher(pw).find()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "密码不能包含中文/日文/韩文字符");
        }
        // Python: if req.confirm and pw != req.confirm（confirm 为空则跳过）
        if (hasText(confirm) && !pw.equals(confirm)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "两次密码不一致");
        }

        // 读-改-写整体加锁，避免并发注册互相覆盖
        synchronized (this) {
            Map<String, Object> users = loadUsers();
            if (users.containsKey(uname)) {
                throw new ResponseStatusException(HttpStatus.CONFLICT, "用户名已存在");
            }
            Map<String, String> hashResult = hashPassword(pw, null);
            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("hash", hashResult.get("hash"));
            entry.put("salt", hashResult.get("salt"));
            entry.put("created_at", LocalDateTime.now().format(CREATED_AT_FORMAT));
            users.put(uname, entry);
            saveUsers(users);
        }
        return ok(uname);
    }

    // ---------------------------------------------------------------------
    // 校验 / 哈希（public，对应任务要求）
    // ---------------------------------------------------------------------

    /** 用户名校验：3-20 位，仅英文字母、数字、下划线。 */
    public boolean validateUsername(String username) {
        return username != null && USERNAME_RE.matcher(username).matches();
    }

    /** 密码校验：≥8 字符，含字母 + 数字，不含 CJK 字符。 */
    public boolean validatePassword(String password) {
        if (password == null || password.length() < 8) {
            return false;
        }
        if (!PASSWORD_LETTER_RE.matcher(password).find()) {
            return false;
        }
        if (!PASSWORD_DIGIT_RE.matcher(password).find()) {
            return false;
        }
        return !CJK_RE.matcher(password).find();
    }

    /**
     * SHA-256(password + salt)，返回 {@code {"hash": ..., "salt": ...}}。
     * {@code salt} 为空时自动生成（Python {@code _hash_pw()}）。
     */
    public Map<String, String> hashPassword(String password, String salt) {
        String s = (salt == null || salt.isBlank()) ? generateSalt() : salt;
        String hash = sha256Hex(str(password) + s);
        Map<String, String> result = new LinkedHashMap<>();
        result.put("hash", hash);
        result.put("salt", s);
        return result;
    }

    /** 生成 16 位十六进制 salt：SHA-256(nanoTime).hex()[:16]（Python 行为）。 */
    public String generateSalt() {
        return sha256Hex(String.valueOf(System.nanoTime())).substring(0, 16);
    }

    // ---------------------------------------------------------------------
    // users.json 存取（Python _load_users / _save_users）
    // ---------------------------------------------------------------------

    private Path usersFile() {
        return Path.of(appConfig.dataDir(), "users.json");
    }

    /** 加载用户表；文件缺失/损坏时重建 demo 账号并落盘。 */
    private Map<String, Object> loadUsers() {
        Path file = usersFile();
        if (Files.isRegularFile(file)) {
            try {
                return objectMapper.readValue(file.toFile(),
                        new TypeReference<LinkedHashMap<String, Object>>() {});
            } catch (IOException e) {
                log.warn("users.json 解析失败，重建 demo 账号: {}", e.getMessage());
            }
        }
        // 首次启动：创建 demo 账号
        Map<String, Object> demo = new LinkedHashMap<>();
        Map<String, String> hashResult = hashPassword(DEMO_PASSWORD, null);
        demo.put("hash", hashResult.get("hash"));
        demo.put("salt", hashResult.get("salt"));
        demo.put("created_at", LocalDateTime.now().format(CREATED_AT_FORMAT));
        Map<String, Object> users = new LinkedHashMap<>();
        users.put(DEMO_USERNAME, demo);
        saveUsers(users);
        return users;
    }

    private void saveUsers(Map<String, Object> users) {
        try {
            Path file = usersFile();
            Files.createDirectories(file.getParent());
            objectMapper.writerWithDefaultPrettyPrinter().writeValue(file.toFile(), users);
        } catch (IOException e) {
            throw new IllegalStateException("无法保存 users.json: " + e.getMessage(), e);
        }
    }

    // ---------------------------------------------------------------------
    // 工具方法
    // ---------------------------------------------------------------------

    private static Map<String, Object> ok(String username) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("status", "ok");
        result.put("username", username);
        return result;
    }

    /** SHA-256 十六进制（小写），与 Python {@code hashlib.sha256(...).hexdigest()} 一致。 */
    private static String sha256Hex(String input) {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            byte[] digest = md.digest(input.getBytes(StandardCharsets.UTF_8));
            StringBuilder sb = new StringBuilder(digest.length * 2);
            for (byte b : digest) {
                sb.append(Character.forDigit((b >> 4) & 0xf, 16));
                sb.append(Character.forDigit(b & 0xf, 16));
            }
            return sb.toString();
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 不可用", e);
        }
    }

    private static String strip(String s) {
        return s == null ? "" : s.strip();
    }

    private static String str(Object v) {
        return v == null ? "" : String.valueOf(v);
    }

    private static boolean hasText(String s) {
        return s != null && !s.isBlank();
    }
}
