# Use Python 3.10 slim image as base
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy only files needed for package installation first
COPY pyproject.toml README.md ./

# Copy application code and configs
COPY src/ ./src/
COPY configs/ ./configs/

# Install Python dependencies
RUN pip install --no-cache-dir . \
    && rm -rf ~/.cache/pip/*

# Create non-root user and switch to it
RUN useradd -m -r appuser \
    && chown -R appuser:appuser /app
USER appuser

# Set default command
ENTRYPOINT ["news-briefing"]