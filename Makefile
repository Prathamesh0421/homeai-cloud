.PHONY: help lint lint-py lint-web test test-common web migrate test-c3-int seed-c4 seed-c2 deploy deploy-env deploy-down deploy-logs

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

# C4 owns its own seed until the master scripts/seed.py (P0-10) lands. Migrations first:
# the seed only writes rows (as c4_app, from DATABASE_URL_C4).
seed-c4:
	cd services/c4_dashboard && alembic upgrade head && PYTHONPATH=$(CURDIR) $(PYTHON) -m app.seed

# C2's part of the seed: the tenant default alert rules (one per alert type) for the seed
# tenants in scripts/seed_ids.py. Migrations first; idempotent (as c2_app, DATABASE_URL_C2).
# In the stack: docker compose -f infra/docker-compose.yml exec c2-alerts python -m app.seed
seed-c2:
	cd services/c2_alerts && alembic upgrade head && $(PYTHON) -m app.seed

# --- AWS / EC2 deploy (C4-16) ---------------------------------------------
# Render a production .env from the provisioned AWS resources. Run on the EC2
# host (or anywhere with an instance profile) and redirect to .env:
#   RDS_ENDPOINT=db.xxxx.rds.amazonaws.com:5432 TEAM=cmpe281 SITE_ADDRESS=homeai.duckdns.org \
#     make deploy-env > .env
COMPOSE_PROD ?= docker compose -f infra/docker-compose.yml -f infra/docker-compose.prod.yml
# Services behind a compose profile are not started without it: the gateway (Caddy) and C3
# always, C1 once services/c1_iot exists, and the Postgres container only when SKIP_RDS=1.
PROD_PROFILES = --profile gateway --profile c3 \
	$(if $(wildcard services/c1_iot/Dockerfile),--profile c1) \
	$(if $(SKIP_RDS),--profile local-postgres-fallback)
deploy-env:
	@infra/aws/render_env.sh

# Build and start the full stack on the EC2 host with the prod overlay.
# Real S3/SNS/Secrets Manager come from the EC2 IAM role; no LocalStack.
# The data layer starts first so set_passwords.sh can give the database roles and Mongo users
# their Secrets Manager passwords (the ones render_env.sh wrote into .env) before the services
# connect. SKIP_RDS=1 make deploy uses the Postgres container instead of RDS.
deploy:
	$(COMPOSE_PROD) $(PROD_PROFILES) up -d --wait mongo $(if $(SKIP_RDS),postgres)
	COMPOSE_PROD="$(COMPOSE_PROD)" SKIP_RDS=$(SKIP_RDS) infra/aws/set_passwords.sh
	$(COMPOSE_PROD) $(PROD_PROFILES) up -d --build

# Stop the prod stack (containers remain). Use `down -v` to also drop volumes.
deploy-down:
	$(COMPOSE_PROD) $(PROD_PROFILES) down

# Tail logs for the prod stack.
deploy-logs:
	$(COMPOSE_PROD) $(PROD_PROFILES) logs -f --tail=100
