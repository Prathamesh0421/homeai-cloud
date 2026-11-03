FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Shared library first so image layers cache when only the service changes.
COPY libs/homeai_common /opt/homeai_common
RUN pip install /opt/homeai_common

COPY services/c2_alerts/pyproject.toml ./
RUN pip install .

COPY services/c2_alerts ./

RUN useradd --system --uid 10002 c2 && chown -R c2 /app
USER c2

ENV RUN_MIGRATIONS=0
EXPOSE 8002

CMD ["sh", "-c", "if [ \"$RUN_MIGRATIONS\" = \"1\" ]; then alembic upgrade head; fi; exec uvicorn --factory app.main:create_app --host 0.0.0.0 --port 8002 --proxy-headers --forwarded-allow-ips='*'"]
