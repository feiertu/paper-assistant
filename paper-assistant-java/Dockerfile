# =============================================================================
# Paper Assistant — Java 后端 (Spring Boot 3.4 / Java 21)
#
# 多阶段构建：
#   1. maven:3.9-eclipse-temurin-21   编译打包（下载依赖为独立缓存层）
#   2. eclipse-temurin:21-jre         精简运行镜像，非 root 用户
#
# ⚠ 构建上下文必须设为仓库根目录（见 docker-compose.yml 的 build.context: ..），
#   因为需要同时访问 paper-assistant-java/（源码）与 frontend/dist（前端产物）。
#
# 前端产物在构建阶段烤进 jar 的 BOOT-INF/classes/static/，使 jar 自包含地托管
# SPA（Spring Boot 默认从 classpath:/static/ 提供静态资源）；运行阶段另复制一份
# 到 /app/static 供直接引用（如 nginx 卷挂载）。
# =============================================================================

# ── Stage 1: 构建 ─────────────────────────────────────────────────────────────
FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /build

# 仅先复制 pom.xml，让依赖下载成为独立缓存层（后续源码改动不会触发重新下载）
COPY paper-assistant-java/pom.xml .
RUN mvn -B -q dependency:go-offline

# 源码 + 预构建前端产物（前端需先执行：cd frontend && npm run build）
COPY paper-assistant-java/src ./src
COPY frontend/dist ./src/main/resources/static

# 打包（跳过测试）；finalName=paper-assistant → target/paper-assistant.jar
RUN mvn -B -DskipTests -Dproject.build.finalName=paper-assistant clean package

# ── Stage 2: 运行 ─────────────────────────────────────────────────────────────
FROM eclipse-temurin:21-jre
WORKDIR /app

# 非 root 用户（uid/gid 1000，与旧 Python 镜像约定一致）
RUN groupadd -r -g 1000 paper && useradd -r -g paper -u 1000 -d /app paper

# 可执行 fat jar（*.jar 只会匹配到 repackaged jar，不含 *.jar.original）
COPY --from=build /build/target/*.jar /app/paper-assistant.jar

# 前端静态资源（独立一份；jar 内也内置了一份）
COPY frontend/dist /app/static

# 数据目录：旧 Python 数据会由 docker-compose 挂载到 /app/data（users.json 等）
RUN mkdir -p /app/data && chown -R paper:paper /app

USER paper

# 与 application.yml 占位符对齐；compose 中可再覆盖
ENV API_PORT=8080 \
    PAPER_ASSISTANT_DATA_DIR=/app/data \
    SPRING_DATASOURCE_URL=jdbc:postgresql://postgres:5432/paper_assistant \
    SPRING_DATASOURCE_USERNAME=paper \
    SPRING_DATASOURCE_PASSWORD=paper

EXPOSE 8080

# 端口 liveness 检查（temurin JRE 无 curl/wget，用 bash /dev/tcp）
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD bash -c 'exec 3<>/dev/tcp/127.0.0.1/8080 || exit 1'

ENTRYPOINT ["java", "-jar", "paper-assistant.jar"]
