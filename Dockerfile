# ==============================================================================
# 阶段 1: 前端静态资源构建阶段 (Node.js 20)
# ==============================================================================
FROM node:20-slim AS frontend-builder
WORKDIR /app/frontend

COPY frontend/package.json ./
RUN npm install --registry=https://registry.npmmirror.com

COPY frontend/ ./
RUN npm run build

# ==============================================================================
# 阶段 2: 生产运行环境 (Python 3.12 + 中文字体库支持)
# ==============================================================================
FROM python:3.12-slim

WORKDIR /app

# 1. 安装 Linux 下的中文字体库与必要图形支持库（彻底避免中文生成为方块）
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-noto-cjk \
    fonts-wqy-zenhei \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 2. 安装 Python 后端依赖
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com

# 3. 复制后端代码与必要目录
COPY backend/ ./backend/

# 4. 从阶段 1 复制前端打包产物
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# 5. 创建上传与输出目录
RUN mkdir -p uploads outputs

# 环境变量设置：适配 Render 等云平台的动态 $PORT 端口
ENV PORT=8000
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# 启动命令：自动读取云平台环境变量 $PORT
CMD ["sh", "-c", "python3 -m uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
