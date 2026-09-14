FROM node:22-bookworm-slim AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim-bookworm
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-noto-cjk fonts-dejavu-core tesseract-ocr tesseract-ocr-eng \
    libreoffice-writer libreoffice-impress libreoffice-calc \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./backend/app
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist
RUN useradd --create-home --uid 10001 translator && mkdir -p /app/data && chown translator:translator /app/data
USER translator
ENV PORT=8000 PYTHONUNBUFFERED=1 DATA_DIR=/app/data
EXPOSE 8000
CMD ["sh", "-c", "python -m uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
