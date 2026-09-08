#!/usr/bin/env bash

# ==============================================================================
# 课件/论文智能双语对照翻译系统 一键启动脚本
# 功能：自动定位 Python 环境、启动 FastAPI 后端（内置托管前端网页）并自动打开浏览器
# ==============================================================================

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

echo "============================================================"
echo "🚀 正在启动 课件/论文智能双语对照翻译系统..."
echo "============================================================"

# 优先选择包含完整环境的 Anaconda Python
if [ -f "/opt/anaconda3/bin/python3" ]; then
    PYTHON_CMD="/opt/anaconda3/bin/python3"
elif command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
else
    echo "❌ 错误: 未检测到 Python 3 环境，请先安装 Python！"
    exit 1
fi

echo "✅ 使用 Python 解释器: $($PYTHON_CMD --version) ($PYTHON_CMD)"

# 检查前端打包产物，若未构建则自动构建
if [ ! -d "frontend/dist" ]; then
    echo "📦 首次启动，正在构建前端静态资源..."
    npm --prefix frontend run build
fi

echo "🌐 启动 Web 服务 (端口: 8000)..."
echo "👉 浏览器访问地址: http://127.0.0.1:8000"
echo "按 Ctrl+C 即可安全停止服务。"
echo "============================================================"

# 尝试在后台自动打开浏览器
(sleep 1.5 && open "http://127.0.0.1:8000" 2>/dev/null || true) &

# 启动 Uvicorn 服务
exec "$PYTHON_CMD" -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
