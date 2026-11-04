FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install the shared library first so image layers cache when only the service changes.
COPY libs/homeai_common /opt/homeai_common
RUN pip install --no-cache-dir /opt/homeai_common

COPY services/c4_dashboard/pyproject.toml ./
RUN pip install --no-cache-dir .

COPY services/c4_dashboard ./

ENV RUN_MIGRATIONS=0
EXPOSE 8004

# A failed migration stops the container instead of serving with a missing schema.
CMD ["sh", "-c", "if [ \"$RUN_MIGRATIONS\" = \"1\" ]; then alembic upgrade head || exit 1; fi; exec uvicorn app.main:app --host 0.0.0.0 --port 8004 --proxy-headers"]
