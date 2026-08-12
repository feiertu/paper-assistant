package com.paperassistant.controller;

import com.paperassistant.dto.request.AuthRequest;
import com.paperassistant.service.AuthService;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;

import java.util.Map;

/**
 * 认证端点 — Python {@code src/api/main.py} 的 {@code /auth/login} 与
 * {@code /auth/register}，返回 {@code {"status": "ok", "username": ...}}。
 *
 * <p>{@link AuthService} 为阻塞实现（users.json 文件 I/O），因此通过
 * {@link Schedulers#boundedElastic()} 异步化，避免阻塞 Netty 事件循环。校验失败由
 * AuthService 抛出 {@link org.springframework.web.server.ResponseStatusException}
 * （login→401，register 校验→400，重名→409），由
 * {@link com.paperassistant.config.GlobalExceptionHandler} 转为统一错误信封。
 */
@RestController
public class AuthController {

    private final AuthService authService;

    public AuthController(AuthService authService) {
        this.authService = authService;
    }

    @PostMapping("/auth/login")
    public Mono<Map<String, Object>> login(@RequestBody AuthRequest req) {
        return Mono.fromCallable(() -> authService.login(req.getUsername(), req.getPassword()))
                .subscribeOn(Schedulers.boundedElastic());
    }

    @PostMapping("/auth/register")
    public Mono<Map<String, Object>> register(@RequestBody AuthRequest req) {
        return Mono.fromCallable(() -> authService.register(
                req.getUsername(), req.getPassword(), req.getConfirm()))
                .subscribeOn(Schedulers.boundedElastic());
    }
}
