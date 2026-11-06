FROM python:3.12-slim

# OpenCV, used by the OCR engine, needs these system libraries.
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY keel ./keel
COPY api ./api
COPY web ./web
COPY rules ./rules
COPY config ./config
COPY scripts ./scripts
COPY data/decks ./data/decks
RUN pip install --no-cache-dir .

EXPOSE 8000
CMD ["sh", "-c", "[ -f data/raw/rcrv_ga.pdf ] || scripts/get_data.sh; exec uvicorn api.main:app --host 0.0.0.0 --port 8000"]
