"""C4 FastAPI app factory."""

from __future__ import annotations

from fastapi import FastAPI

from app.api import auth as auth_router
from app.api import contacts as contacts_router
from app.api import health as health_router
from app.api import jwks as jwks_router
from app.api import service_tokens as service_tokens_router
from app.api import settings as settings_router
from app.api import tenants as tenants_router
from app.api import users as users_router
from app.errors import install_error_handlers


def create_app() -> FastAPI:
    app = FastAPI(
        title="HomeAI Cloud — C4 System Dashboard",
        version="0.1.0",
        docs_url="/api/v1/docs/c4",
        redoc_url=None,
        openapi_url="/api/v1/docs/c4/openapi.json",
        swagger_ui_parameters={"persistAuthorization": True},
    )

    install_error_handlers(app)

    app.include_router(health_router.router)
    app.include_router(jwks_router.router)
    app.include_router(auth_router.router)
    app.include_router(service_tokens_router.router)
    app.include_router(settings_router.router)
    app.include_router(contacts_router.router)
    app.include_router(tenants_router.router)
    app.include_router(users_router.router)

    @app.on_event("startup")
    def _configure_jwks() -> None:
        # Build a local JWKS cache from our own signing keys so C4 can verify the
        # tokens it issued without a circular HTTP call to itself. Other
        # services configure an HTTP-backed cache pointing at this app.
        import homeai_common.auth as auth_mod
        from homeai_common.auth import JwksCache

        from app.deps import get_jwt_issuer
        from app.settings import get_settings

        try:
            issuer = get_jwt_issuer(get_settings())
            entries = issuer.jwks()["keys"]
            auth_mod._default_cache = JwksCache.from_entries(entries)
        except Exception:
            pass

    return app


app = create_app()
