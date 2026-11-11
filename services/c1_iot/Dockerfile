FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Shared library first so image layers cache when only the service changes.
COPY libs/homeai_common /opt/homeai_common
RUN pip install /opt/homeai_common

COPY services/c1_iot/pyproject.toml ./
RUN pip install .

COPY services/c1_iot ./

RUN useradd --system --uid 10001 c1 && chown -R c1 /app
USER c1

ENV RUN_MIGRATIONS=0
EXPOSE 8001

# A failed migration stops the container instead of serving on a schema it cannot use.
CMD ["sh", "-c", "if [ \"$RUN_MIGRATIONS\" = \"1\" ]; then alembic upgrade head || exit 1; fi; exec uvicorn --factory app.main:create_app --host 0.0.0.0 --port 8001 --proxy-headers --forwarded-allow-ips='*'"]
