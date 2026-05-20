# syntax=docker/dockerfile:1.4
FROM python:3.12-slim

WORKDIR /app

# Install system deps including C++ compiler for chroma-hnswlib and git for pip VCS deps
RUN apt-get update && apt-get install -y \
    curl \
    gcc \
    g++ \
    cmake \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps — github_token secret used to authenticate private acpcore repo
COPY requirements.txt .
RUN --mount=type=secret,id=github_token \
    GIT_CONFIG_COUNT=1 \
    GIT_CONFIG_KEY_0="url.https://x-access-token:$(cat /run/secrets/github_token)@github.com/.insteadOf" \
    GIT_CONFIG_VALUE_0="https://github.com/" \
    pip install --no-cache-dir -r requirements.txt

# Copy source
COPY api/ ./api/
COPY shared/ ./shared/
COPY services/ ./services/

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
