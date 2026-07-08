#!/bin/bash
# ============================================
# Paper Assistant 一键重新部署脚本
# 在服务器 /opt/paper-assistant 目录下运行
# ============================================
set -e

echo "========================================"
echo " Paper Assistant — 重新部署"
echo " $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================"

# 1. 停止并删除旧容器
echo ""
echo "[1/4] 停止旧容器..."
docker-compose down 2>/dev/null || true
echo "  -> 旧容器已停止"

# 2. 清理冲突文件并拉取最新代码
echo ""
echo "[2/4] 拉取最新代码..."
git checkout -- . 2>/dev/null || true
git clean -fd 2>/dev/null || true
git pull origin main
echo "  -> 代码已更新"

# 3. 重新构建镜像
echo ""
echo "[3/4] 构建新镜像..."
docker-compose build --no-cache 2>&1 | tail -5
echo "  -> 镜像构建完成"

# 4. 启动服务
echo ""
echo "[4/4] 启动服务..."
docker-compose up -d
echo "  -> 服务已启动"

# 等待服务就绪
echo ""
echo "等待服务就绪 (最多 30s)..."
for i in $(seq 1 15); do
    if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        echo "  -> 后端 API 就绪"
        break
    fi
    sleep 2
done

# 显示状态
echo ""
echo "========================================"
echo " 容器状态"
echo "========================================"
docker-compose ps

echo ""
echo "========================================"
echo " 最近日志"
echo "========================================"
docker-compose logs --tail=15

echo ""
echo "========================================"
echo " 部署完成!"
echo " 访问: https://feiertu.xyz"
echo "========================================"
