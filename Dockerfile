# ─── Build stage ─────────────────────────────────────────────────────────────
FROM python:3.11-slim AS base

LABEL maintainer="dhrumit.thakkar@gmail.com"
LABEL description="NSE/BSE OI Spike Monitor"

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create runtime directories
RUN mkdir -p logs data

# ─── Runtime ──────────────────────────────────────────────────────────────────
ENV DATA_SOURCE=YAHOO
ENV POLL_INTERVAL_SECONDS=60
ENV LOG_LEVEL=INFO
ENV RESPECT_MARKET_HOURS=true
ENV CSV_ENABLED=true

# Mount points for persistent logs & CSV data
VOLUME ["/app/logs", "/app/data"]

CMD ["python", "main.py"]
