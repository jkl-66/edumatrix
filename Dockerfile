# =====================================================
# Stage 1: Build Vue frontend
# =====================================================
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci --omit=optional
COPY frontend/ .
RUN npm run build

# =====================================================
# Stage 2: Python backend + serve static frontend
# =====================================================
FROM python:3.11-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl && \
    rm -rf /var/lib/apt/lists/*

# Copy backend code
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Copy built frontend
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

# Ensure SQLite DB directory is writable
RUN mkdir -p /app/data

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -s http://127.0.0.1:8000/api/health || exit 1

# Start with uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
