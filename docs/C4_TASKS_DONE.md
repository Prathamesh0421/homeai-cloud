# C4 tasks done (2 Nov 2026)

Week-1 foundation for Mohit (C4). Other components can verify C4 tokens and the SPA can sign in. C1, C2, and C3 code was not required.

## Done

| ID | What landed |
|---|---|
| P0-2 | Root `pyproject.toml` (ruff), `.env.example`, `Makefile` (`lint`, `test-c4`, `web`, `migrate`) |
| C4-01 | `services/c4_dashboard` FastAPI app, health `GET /api/v1/health/c4`, Dockerfile, Alembic |
| C4-02 | Schema `c4` (tenants, users, `users_public`, service clients, revoked tokens, settings, contacts) and `GET /.well-known/jwks.json` |
| C4-03 | `POST /auth/login` (401 / 423 lockout), `POST /auth/logout`, `GET /auth/me`, `GET /auth/revoked` |
| C4-04 | `POST /auth/service-token` (bcrypt secret, scope subset, 15 min TTL) |
| C4-05 | `libs/homeai_common`: `auth`, `service_client`, `testing` |
| C4-10 | Vite shell: login, session token, `RouteGuard`, role landings, API client |

Tests: 25 C4 + 10 shared-library + 3 web. Login, `/auth/me`, logout, and revocation were checked through the Vite proxy.

## Not in this pass

C4-06 settings and contacts, C4-07 tenants and users, C4-08/09 dashboards and rollup, C4-11 UI kit, C4-12–14 pages, C4-15 seed, C4-16 AWS, C4-17 Playwright. Compose, Caddy, and `scripts/seed.py` stay with their Phase 0 owners.
