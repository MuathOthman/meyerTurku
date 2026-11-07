# Build context is the repo root: see docker-compose.yml.
FROM node:24-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim

# OpenCV, used by the OCR engine, needs these system libraries.
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/pyproject.toml ./
COPY backend/keel ./keel
COPY backend/api ./api
COPY backend/rules ./rules
COPY backend/config ./config
COPY backend/scripts ./scripts
COPY backend/data/decks ./data/decks
COPY --from=frontend /frontend/dist ./frontend/dist
ENV KEEL_FRONTEND_DIST=/app/frontend/dist
RUN pip install --no-cache-dir .

EXPOSE 8000
CMD ["sh", "-c", "[ -f data/raw/rcrv_ga.pdf ] || scripts/get_data.sh; exec uvicorn api.main:app --host 0.0.0.0 --port 8000"]
