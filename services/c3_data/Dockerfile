FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    C3_MODEL_DIR=/models \
    TFHUB_CACHE_DIR=/tmp/tfhub

WORKDIR /app

# System packages: ffmpeg decodes clips to 16 kHz mono; libsndfile backs soundfile.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Shared library first so image layers cache when only the service changes.
COPY libs/homeai_common /opt/homeai_common
RUN pip install /opt/homeai_common

# Service dependencies (TensorFlow is the heavy layer; cache it before app code).
COPY services/c3_data/pyproject.toml ./
RUN pip install .

# Download and bundle YAMNet at build time so the container starts offline.
COPY scripts/download_yamnet.py /opt/download_yamnet.py
RUN python /opt/download_yamnet.py --target "$C3_MODEL_DIR" \
    && rm -rf /tmp/tfhub

# Application code last.
COPY services/c3_data ./

# Non-root runtime user; owns /app and the bundled model.
RUN useradd --system --uid 10003 c3 \
    && chown -R c3 /app "$C3_MODEL_DIR"
USER c3

ENV RUN_MIGRATIONS=0
EXPOSE 8003

CMD ["sh", "-c", "if [ \"$RUN_MIGRATIONS\" = \"1\" ]; then alembic upgrade head; fi; exec uvicorn --factory app.main:create_app --host 0.0.0.0 --port 8003 --proxy-headers --forwarded-allow-ips='*'"]
