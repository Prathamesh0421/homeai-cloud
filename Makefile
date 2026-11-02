.PHONY: help lint lint-py lint-web test test-c4 web migrate

PYTHON ?= python3
PYTEST ?= pytest
RUFF ?= ruff

help:
	@echo "HomeAI Cloud (Phase 0). Available targets:"
	@echo "  make lint        ruff + eslint + tsc"
	@echo "  make test        pytest across all services"
	@echo "  make test-c4     pytest for services/c4_dashboard only"
	@echo "  make web         run Vite dev server (web/)"
	@echo "  make migrate     run Alembic for every service (once they exist)"

lint: lint-py lint-web

lint-py:
	$(RUFF) check .
	$(RUFF) format --check .

lint-web:
	@if [ -d web/node_modules ]; then cd web && npm run lint && npm run typecheck; else \
		echo "web/ not installed; run 'cd web && npm install' first"; fi

test:
	$(PYTEST)

test-c4:
	cd services/c4_dashboard && $(PYTEST) -q

web:
	cd web && npm run dev

migrate:
	@for svc in services/*; do \
		if [ -f $$svc/alembic.ini ]; then \
			echo "Migrating $$svc"; \
			cd $$svc && alembic upgrade head && cd -; \
		fi; \
	done
