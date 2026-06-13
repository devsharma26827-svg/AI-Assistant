# Multi-stage build for optimal image size
FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install web server dependencies only (avoiding Windows-only libs from requirement.txt)
RUN pip install --no-cache-dir --user \
    fastapi \
    uvicorn \
    pydantic \
    python-multipart \
    websockets \
    requests \
    qrcode

# Final runtime image
FROM python:3.11-slim AS runner

WORKDIR /app

# Copy installed packages from builder stage
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Copy project files needed for the Brain Server
COPY device_server.py .
COPY templates/ ./templates/

# Expose FastAPI Brain Server default port
EXPOSE 8000

# Run the brain server
CMD ["python", "device_server.py"]
