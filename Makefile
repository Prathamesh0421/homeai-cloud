.PHONY: help lint lint-py lint-web test test-common web migrate test-c3-int

PYTHON ?= python3
PYTEST ?= pytest
RUFF ?= ruff

help:
	@echo "HomeAI Cloud (Phase 0). Available targets:"
	@echo "  make lint        ruff + eslint + tsc"
	@echo "  make test        pytest for libs/homeai_common and every service"
	@echo "  make test-common pytest for libs/homeai_common only"
	@echo "  make test-c4     pytest for one service (test-c1 .. test-c4)"
	@echo "  make web         run Vite dev server (web/)"
	@echo "  make migrate     run Alembic for every service (once they exist)"

lint: lint-py lint-web

lint-py:
	$(RUFF) check .
	$(RUFF) format --check .

lint-web:
	@if [ -d web/node_modules ]; then cd web && npm run lint && npm run typecheck; else \
		echo "web/ not installed; run 'cd web && npm install' first"; fi

# Each package runs separately: libs/ and services/ both have a top-level `tests` package,
# so collecting them together from the repo root fails.
test:
	@status=0; for pkg in libs/homeai_common services/*; do \
		if [ -f $$pkg/pyproject.toml ]; then \
			echo "== $$pkg"; (cd $$pkg && $(PYTEST) -q) || status=1; \
		fi; \
	done; exit $$status

test-common:
	cd libs/homeai_common && $(PYTEST) -q

test-c%:
	cd services/c$*_* && $(PYTEST) -q

# C3 Tier 2 integration tests against real Postgres + Mongo + LocalStack (brought up via
# docker compose). Exports the same env the CI job uses, then tears the stack down.
COMPOSE ?= docker compose -f infra/docker-compose.yml
test-c3-int:
	$(COMPOSE) up -d postgres mongo localstack
	@echo "waiting for infra..."; sleep 8
	cd services/c3_data && \
	  DATABASE_URL_C3=postgresql+psycopg://c3_app:devpass@localhost:5432/homeai \
	  MONGO_URL_C3=mongodb://c3_app:devpass@localhost:27017/homeai?authSource=homeai \
	  S3_BUCKET=homeai-local AWS_REGION=us-west-2 AWS_ENDPOINT_URL=http://localhost:4566 \
	  AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test \
	  $(PYTEST) -q -m integration; status=$$?; \
	  cd ../.. && $(COMPOSE) down -v; exit $$status

web:
	cd web && npm run dev

migrate:
	@for svc in services/*; do \
		if [ -f $$svc/alembic.ini ]; then \
			echo "Migrating $$svc"; \
			cd $$svc && alembic upgrade head && cd -; \
		fi; \
	done
