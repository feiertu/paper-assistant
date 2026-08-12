package com.paperassistant.config;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.BindingResult;
import org.springframework.validation.FieldError;
import org.springframework.validation.ObjectError;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.bind.support.WebExchangeBindException;
import org.springframework.web.server.ResponseStatusException;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Global exception handler that turns every failure into the unified error
 * envelope the Python FastAPI service uses:
 *
 * <pre>{@code {"error": {"code": <status>, "message": "<detail>"}}}</pre>
 *
 * <p>Handles three families of exceptions:
 * <ul>
 *   <li>{@link ResponseStatusException} — status + reason passthrough (the
 *       Java equivalent of FastAPI's {@code HTTPException});</li>
 *   <li>{@link MethodArgumentNotValidException} (Spring MVC) and
 *       {@link WebExchangeBindException} (Spring WebFlux, the exception actually
 *       thrown by {@code @Valid} on a reactive controller) — field-level
 *       validation errors, always reported as HTTP 422;</li>
 *   <li>any other {@link Exception} — a fixed 500 body so internals are never
 *       leaked to clients.</li>
 * </ul>
 *
 * <p>4xx failures are logged at WARN, 5xx failures at ERROR (with stack trace).
 */
@RestControllerAdvice
public class GlobalExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    @ExceptionHandler(ResponseStatusException.class)
    public ResponseEntity<Map<String, Object>> handleResponseStatus(ResponseStatusException ex) {
        int code = ex.getStatusCode().value();
        String message = (ex.getReason() != null && !ex.getReason().isBlank())
                ? ex.getReason()
                : "HTTP " + code;
        if (code >= 500) {
            log.error("Server error {}: {}", code, message, ex);
        } else {
            log.warn("Request rejected {}: {}", code, message);
        }
        return error(ex.getStatusCode(), message);
    }

    /** Spring MVC validation path (kept for parity; WebFlux uses the next handler). */
    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<Map<String, Object>> handleMethodValidation(MethodArgumentNotValidException ex) {
        String message = validationMessage(ex.getBindingResult());
        log.warn("Validation failed: {}", message);
        return error(HttpStatus.UNPROCESSABLE_ENTITY, message);
    }

    /** Spring WebFlux validation path ({@code @Valid} on a reactive request body). */
    @ExceptionHandler(WebExchangeBindException.class)
    public ResponseEntity<Map<String, Object>> handleWebExchangeValidation(WebExchangeBindException ex) {
        String message = validationMessage(ex.getBindingResult());
        log.warn("Validation failed: {}", message);
        return error(HttpStatus.UNPROCESSABLE_ENTITY, message);
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<Map<String, Object>> handleGeneric(Exception ex) {
        log.error("Unhandled exception", ex);
        return error(HttpStatus.INTERNAL_SERVER_ERROR, "Internal server error");
    }

    /** Collapses a Spring {@link BindingResult} into a single human-readable message. */
    private static String validationMessage(BindingResult binding) {
        List<String> parts = new ArrayList<>();
        for (FieldError fe : binding.getFieldErrors()) {
            String detail = fe.getDefaultMessage() != null ? fe.getDefaultMessage() : "invalid value";
            parts.add(fe.getField() + ": " + detail);
        }
        for (ObjectError oe : binding.getGlobalErrors()) {
            if (oe.getDefaultMessage() != null) {
                parts.add(oe.getDefaultMessage());
            }
        }
        return parts.isEmpty() ? "Validation failed" : String.join("; ", parts);
    }

    private static ResponseEntity<Map<String, Object>> error(HttpStatusCode status, String message) {
        Map<String, Object> error = new LinkedHashMap<>();
        error.put("code", status.value());
        error.put("message", message);
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("error", error);
        return ResponseEntity.status(status).body(body);
    }
}
