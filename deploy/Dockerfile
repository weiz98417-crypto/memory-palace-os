# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Stage 1: builder — 安装依赖，不污染最终镜像
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ARG PYTHON_BASE_IMAGE=python:3.11-slim
ARG LOCAL_EMBEDDINGS=false

FROM ${PYTHON_BASE_IMAGE} AS builder

WORKDIR /build

# 系统依赖（编译期）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 先复制依赖文件，利用 Docker 层缓存
COPY requirements.txt requirements-scenic-agent-local-embeddings.txt .
ARG LOCAL_EMBEDDINGS=false
RUN pip install --upgrade pip && \
    pip install --prefix=/install --no-cache-dir -r requirements.txt && \
    if [ "$LOCAL_EMBEDDINGS" = "true" ]; then \
        pip install --prefix=/install --no-cache-dir -r requirements-scenic-agent-local-embeddings.txt; \
    fi


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Stage 2: runtime — 最终运行镜像，尽可能精简
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FROM ${PYTHON_BASE_IMAGE} AS runtime

LABEL maintainer="memory-palace-os"
LABEL description="文旅多智能体运营系统"

# 运行时系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 从 builder 拷贝已安装的 Python 包
COPY --from=builder /install /usr/local

# 创建非 root 运行用户（安全加固）
RUN groupadd -r appuser && useradd -r -m -d /home/appuser -g appuser appuser

WORKDIR /app

# 复制项目源码
COPY --chown=appuser:appuser . .

# 创建数据目录（volumes 会覆盖，但保证目录存在）
RUN mkdir -p data/logs /models/huggingface && \
    chown -R appuser:appuser /app /home/appuser

USER appuser

# 环境变量默认值（可被 docker-compose / .env 覆盖）
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    HOME=/home/appuser \
    APP_ENV=production \
    LOG_LEVEL=INFO

# 健康检查（对应 main.py 的 /health 端点）
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

# 生产启动命令：单 worker（asyncio 不需要多 worker）
# --forwarded-allow-ips 信任 nginx 的 X-Forwarded-For
CMD ["gunicorn", "main:app", \
     "-k", "uvicorn.workers.UvicornWorker", \
     "-w", "1", \
     "--bind", "0.0.0.0:8000", \
     "--timeout", "120", \
     "--keep-alive", "5", \
     "--forwarded-allow-ips", "*", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
