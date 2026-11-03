"""``GET /api/v1/health/<cx>`` (contracts §1; no auth).

Body: ``{"status": "ok", "db": "ok", "mongo": "ok", "version": "<git sha>"}``. Each named check
is a callable that raises on failure. If any check fails the body says ``"status": "degraded"``
with that check ``"error"`` and the HTTP status is **503**, so compose ``service_healthy`` and
``curl -f`` treat the service as down.

    app.include_router(health_router(
        "c2",
        {"db": check_database, "mongo": lambda: check_mongo(detections_db)},
        version=settings.git_sha,
    ))
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping

from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger("homeai_common.health")

HealthCheck = Callable[[], object]


def run_checks(checks: Mapping[str, HealthCheck]) -> dict[str, str]:
    results: dict[str, str] = {}
    for name, check in checks.items():
        try:
            check()
            results[name] = "ok"
        except Exception as exc:
            logger.warning("health check failed", extra={"check": name, "error": str(exc)[:200]})
            results[name] = "error"
    return results


def health_router(
    service_name: str, checks: Mapping[str, HealthCheck], *, version: str = "dev"
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/health", tags=["health"])

    # Sync handler on purpose: blocking DB/Mongo checks run in FastAPI's threadpool.
    @router.get(f"/{service_name}", summary=f"{service_name} health")
    def health() -> JSONResponse:
        results = run_checks(checks)
        healthy = all(v == "ok" for v in results.values())
        body = {"status": "ok" if healthy else "degraded", **results, "version": version}
        return JSONResponse(status_code=200 if healthy else 503, content=body)

    return router
