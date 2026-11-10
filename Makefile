.PHONY: help lint lint-py lint-web test test-common web migrate test-c3-int seed-c4 seed-c2 seed-c1 seed-c1-docker deploy deploy-env deploy-down deploy-logs demo-c2-detect demo-c2-expired-link demo-c2-quiet-hours demo-c2-reset baseline-run integrity-run test-c2-full test-c1-full

PYTHON ?= python3
PYTEST ?= pytest
RUFF ?= ruff

help:
	@echo "HomeAI Cloud (Phase 0). Available targets:"
	@echo "  make lint        ruff + eslint + tsc"
	@echo "  make test        pytest for libs/homeai_common and every service"
	@echo "  make test-common pytest for libs/homeai_common only"
	@echo "  make test-c4     pytest for one service (test-c1 .. test-c4)"
	@echo "  make test-c2-full  C2 tests + coverage against real Postgres/Mongo/LocalStack containers"
	@echo "  make test-c1-full  C1 tests + coverage against real Postgres/Mongo/LocalStack containers"
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

# C2's full suite with coverage against real Postgres/Mongo/LocalStack containers on spare ports
# (reused between runs; the demo's "unit tests running" step). Plain `make test-c2` skips the
# store-backed tests when no database is configured.
test-c2-full:
	PYTHON=$(PYTHON) scripts/test_c2.sh $(ARGS)

# Same for C1 (its own containers on other spare ports).
test-c1-full:
	PYTHON=$(PYTHON) scripts/test_c1.sh $(ARGS)

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
# On EC2 (no local alembic): use `make seed-c4-docker` after the stack is up.
seed-c4:
	cd services/c4_dashboard && alembic upgrade head && PYTHONPATH=$(CURDIR) $(PYTHON) -m app.seed

# Run migrations + seed inside the already-built c4 image (EC2). Mounts the
# repo so scripts/seed_ids.py is importable.
seed-c4-docker:
	$(COMPOSE_PROD) exec -T c4-dashboard alembic upgrade head
	$(COMPOSE_PROD) run --rm --no-deps \
		-v $(CURDIR):/workspace:ro \
		-e PYTHONPATH=/workspace \
		-w /app \
		c4-dashboard python -m app.seed

# C2's part of the seed: the tenant default alert rules (one per alert type) for the seed
# tenants in scripts/seed_ids.py. Migrations first; idempotent (as c2_app, DATABASE_URL_C2).
# In the stack: docker compose -f infra/docker-compose.yml exec c2-alerts python -m app.seed
seed-c2:
	cd services/c2_alerts && alembic upgrade head && $(PYTHON) -m app.seed

# C1's part of the seed: houses, rooms and feeds with the fixed IDs of scripts/seed_ids.py.
# Migrations first; idempotent (as c1_app, DATABASE_URL_C1). Run it before seed-c2/seed-c4's
# house references are used (C2 answers 503 until c1.houses exists).
seed-c1:
	cd services/c1_iot && alembic upgrade head && PYTHONPATH=$(CURDIR) $(PYTHON) -m app.seed

# The same inside the c1-iot image on EC2 (host has no Python), repo mounted for seed_ids.py.
seed-c1-docker:
	$(COMPOSE_PROD) exec -T c1-iot alembic upgrade head
	$(COMPOSE_PROD) run --rm --no-deps \
		-v $(CURDIR):/workspace:ro \
		-e PYTHONPATH=/workspace \
		-w /app \
		c1-iot python -m app.seed

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

# --- C2 demo helpers (C2 plan §10.1) --------------------------------------------------------
# For the EC2 host: the host has no Python and Mongo is not published, so the scripts run in the
# c2-alerts / c4-dashboard images on the compose network, with the repo mounted read-only and
# the host's .env. Locally: COMPOSE_PROD="docker compose -f infra/docker-compose.yml".
#   make demo-c2-detect ARGS="--label glass_break --conf 0.78"   (then ARGS="--resend <id>")
#   make demo-c2-expired-link                                     (newest alert)
#   make demo-c2-quiet-hours ARGS=--cover-now                     (or --set 22:00-07:00, --off, --show)
#   make demo-c2-reset ARGS=--yes                                 (alerts only; rules/SNS kept)
C2_DEMO_RUN = $(COMPOSE_PROD) run --rm --no-deps -T -v $(CURDIR):/workspace:ro -w /workspace
demo-c2-detect:
	$(C2_DEMO_RUN) -e HOMEAI_API_URL=http://caddy:80 c2-alerts python scripts/demo/c2_fake_detection.py $(ARGS)

demo-c2-expired-link:
	$(C2_DEMO_RUN) c2-alerts python scripts/demo/c2_expired_link.py $(ARGS)

demo-c2-quiet-hours:
	$(C2_DEMO_RUN) -e PYTHONPATH=/app c4-dashboard python scripts/demo/c2_quiet_hours.py $(ARGS)

demo-c2-reset:
	$(COMPOSE_PROD) exec -T c2-alerts python -m app.demo_reset $(ARGS)

# --- C3 demo helpers (C3 plan §10) ----------------------------------------------------------
# Run the activity-baseline job on demand so the Activity chart shows a baseline band and an
# anomaly badge without waiting for the nightly clock (the shared scheduler lands in 8c).
# Runs in the c3-data image on the compose network, repo mounted, using the host .env.
#   make baseline-run                         (as of now)
#   make baseline-run ARGS="--as-of 2026-07-01T12:00:00Z"
baseline-run:
	$(COMPOSE_PROD) run --rm --no-deps -T -v $(CURDIR):/workspace:ro -e PYTHONPATH=/app \
		c3-data python /workspace/scripts/demo/c3_baseline.py $(ARGS)

# Run the C3 integrity check on demand (C3-12). The nightly scheduler runs this across all
# tenants; this trigger lets demo prep run it without waiting for the clock. It records an
# integrity_reports row and prints a findings-by-severity summary.
#   make integrity-run                        (all tenants, records a report)
#   make integrity-run ARGS="--tenant-id <uuid>"   (one tenant, no report row)
integrity-run:
	$(COMPOSE_PROD) run --rm --no-deps -T -v $(CURDIR):/workspace:ro -e PYTHONPATH=/app \
		c3-data python /workspace/scripts/demo/c3_integrity.py $(ARGS)
