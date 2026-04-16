# ─── Build stage ─────────────────────────────────────────────────────────────
FROM python:3.11-slim AS base

LABEL maintainer="your_email@example.com"
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
# FIX #19: .dockerignore must exist alongside this Dockerfile to exclude
#   .env, logs/, data/, __pycache__/ from the build context.
#   See .dockerignore in the project root.
COPY . .

# Create runtime directories
RUN mkdir -p logs data

# ─── Runtime ──────────────────────────────────────────────────────────────────
# FIX #20: TZ is set here (was missing in original Dockerfile despite the comment)
ENV TZ=Asia/Kolkata
ENV DATA_SOURCE=YAHOO
ENV POLL_INTERVAL_SECONDS=60
ENV LOG_LEVEL=INFO
ENV RESPECT_MARKET_HOURS=true
ENV CSV_ENABLED=true

# Mount points for persistent logs & CSV data
VOLUME ["/app/logs", "/app/data"]

CMD ["python", "main.py"]
