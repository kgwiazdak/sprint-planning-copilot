# Build stage - use Poetry to export dependencies
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    POETRY_VERSION=2.2.1 \
    POETRY_NO_INTERACTION=1

RUN pip install --upgrade pip \
 && pip install "poetry==${POETRY_VERSION}" \
 && poetry self add poetry-plugin-export

WORKDIR /app

COPY pyproject.toml poetry.lock ./
RUN poetry export -f requirements.txt -o requirements.txt --without-hashes --only main

# Runtime stage - minimal image
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Install only runtime dependencies
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    libasound2 \
    ca-certificates \
    ffmpeg \
 && rm -rf /var/lib/apt/lists/* \
 && apt-get clean

WORKDIR /app

# Copy requirements from builder and install
COPY --from=builder /app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && rm requirements.txt

# Copy application code
COPY backend backend
COPY data data

EXPOSE 8000
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
