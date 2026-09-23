# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Stage 1: builder — 安装依赖，不污染最终镜像
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ARG PYTHON_BASE_IMAGE=python:3.11-slim
ARG NODE_IMAGE=node:24.15.0-bookworm-slim
ARG NPM_REGISTRY=https://registry.npmjs.org
ARG LOCAL_EMBEDDINGS=false

FROM ${PYTHON_BASE_IMAGE} AS builder

WORKDIR /build

# 系统依赖（编译期）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 先复制依赖文件，利用 Docker 层缓存
COPY requirements.lock requirements-scenic-agent-local-embeddings.txt .
ARG LOCAL_EMBEDDINGS=false
RUN pip install --upgrade pip && \
    pip install --prefix=/install --no-cache-dir -r requirements.lock && \
    if [ "$LOCAL_EMBEDDINGS" = "true" ]; then \
        pip install --prefix=/install --no-cache-dir -r requirements-scenic-agent-local-embeddings.txt; \
    fi


# Export the real FastAPI contract for the frontend type check.
# The build must not assume that a host-side API is already running.
COPY . .
ENV PYTHONPATH=/install/lib/python3.11/site-packages
RUN python scripts/export_openapi.py /tmp/openapi.json


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Stage 2: frontend builder — build Vite apps from source
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FROM ${NODE_IMAGE} AS frontend-builder
ARG NPM_REGISTRY

WORKDIR /frontend
RUN npm install -g pnpm@11.19.0

COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml frontend/.npmrc frontend/tsconfig.json frontend/vite.shared.ts frontend/vitest.config.ts frontend/eslint.config.js ./
COPY frontend/apps ./apps
COPY frontend/packages ./packages
COPY frontend/scripts ./scripts

RUN pnpm config set registry "$NPM_REGISTRY" && pnpm install --frozen-lockfile
COPY --from=builder /tmp/openapi.json /tmp/openapi.json
RUN OPENAPI_FILE=/tmp/openapi.json pnpm build && \
    test -f /static/client/console/index.html && \
    test -f /static/client/field/index.html && \
    test -f /static/client/integration/index.html && \
    test -f /static/client/operations/index.html


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Optional offline frontend build — uses dependency cache only, never prebuilt app output
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FROM ${NODE_IMAGE} AS frontend-builder-offline
WORKDIR /frontend
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml frontend/.npmrc frontend/tsconfig.json frontend/vite.shared.ts frontend/vitest.config.ts frontend/eslint.config.js ./
COPY frontend/apps ./apps
COPY frontend/packages ./packages
COPY frontend/scripts ./scripts
COPY offline/node_modules.tar.gz /tmp/node_modules.tar.gz
COPY offline/openapi.json /tmp/openapi.json
RUN tar -xzf /tmp/node_modules.tar.gz -C /frontend && \
    OPENAPI_FILE=/tmp/openapi.json node scripts/generate-openapi-types.mjs && \
    (cd apps/console && node ../../node_modules/vite/bin/vite.js build) && \
    (cd apps/field && node ../../node_modules/vite/bin/vite.js build) && \
    (cd apps/integration && node ../../node_modules/vite/bin/vite.js build) && \
    (cd apps/operations && node ../../node_modules/vite/bin/vite.js build) && \
    test -f /static/client/console/index.html && \
    test -f /static/client/field/index.html && \
    test -f /static/client/integration/index.html && \
    test -f /static/client/operations/index.html

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Stage 3: runtime — 最终运行镜像，尽可能精简
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

# 复制项目源码和由源码构建的 V2 前端产物
COPY --chown=appuser:appuser . .
COPY --from=frontend-builder --chown=appuser:appuser /static/client /app/static/client

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
CMD ["sh", "-c", "exec gunicorn main:app -k uvicorn.workers.UvicornWorker -w 1 --bind 0.0.0.0:8000 --timeout 120 --keep-alive 5 --forwarded-allow-ips \"${FORWARDED_ALLOW_IPS:-127.0.0.1}\" --access-logfile - --error-logfile -"]
