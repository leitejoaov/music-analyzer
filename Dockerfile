FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY analyzer/__init__.py analyzer/meta.py analyzer/download_models.py ./analyzer/
RUN python -m analyzer.download_models

COPY analyzer/ ./analyzer/

EXPOSE 5001

# Analysis is CPU-bound, so throughput scales with worker processes (gunicorn reads WEB_CONCURRENCY).
# Each worker loads its own models (~1.3 GB RAM); a track can take well over gunicorn's default 30s timeout.
ENV WEB_CONCURRENCY=3
CMD ["gunicorn", "--timeout", "300", "--bind", "0.0.0.0:5001", "analyzer.app:app"]
