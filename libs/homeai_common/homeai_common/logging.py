"""JSON logging and request-id propagation (contracts §1, §6).

Log lines are JSON on stdout with ``ts, level, service, request_id, tenant_id, user_id, msg``
plus any ``extra={...}`` fields. Never log passwords, tokens or full emails (use `mask_email`).

Wire up in ``create_app()``::

    configure_logging("c2-alerts")
    app.add_middleware(RequestIdMiddleware)
"""

from __future__ import annotations

import logging
import re
import sys
import time
import uuid
from contextvars import ContextVar
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

try:  # python-json-logger >= 3
    from pythonjsonlogger.json import JsonFormatter
except ImportError:  # pragma: no cover - python-json-logger 2.x
    from pythonjsonlogger.jsonlogger import JsonFormatter

REQUEST_ID_HEADER = "X-Request-Id"
_SCOPE_STATE_KEY = "request_id"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
tenant_id_var: ContextVar[str | None] = ContextVar("tenant_id", default=None)
user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)

_service_name = "homeai"
access_logger = logging.getLogger("homeai.access")

# LogRecord attributes that are not user "extra" fields.
_RESERVED = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}
_TOP_LEVEL = ("ts", "level", "service", "request_id", "tenant_id", "user_id", "msg")


class ContextFilter(logging.Filter):
    """Copies the request context vars onto every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.service = _service_name
        record.request_id = request_id_var.get()
        record.tenant_id = tenant_id_var.get()
        record.user_id = user_id_var.get()
        return True


class HomeAiJsonFormatter(JsonFormatter):
    """Emits the contract field names and nests user extras under ``extra``."""

    def add_fields(
        self, log_record: dict[str, Any], record: logging.LogRecord, message_dict: dict[str, Any]
    ) -> None:
        log_record["ts"] = (
            time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z"
        )
        log_record["level"] = record.levelname
        log_record["service"] = getattr(record, "service", _service_name)
        log_record["request_id"] = getattr(record, "request_id", None)
        log_record["tenant_id"] = getattr(record, "tenant_id", None)
        log_record["user_id"] = getattr(record, "user_id", None)
        log_record["msg"] = record.getMessage()
        extra = {
            k: v
            for k, v in vars(record).items()
            if k not in _RESERVED and k not in _TOP_LEVEL and not k.startswith("_")
        }
        extra.update(message_dict)
        if record.exc_info:
            extra["exc_info"] = self.formatException(record.exc_info)
        if extra:
            log_record["extra"] = extra


def configure_logging(service: str, level: str | int = "INFO") -> None:
    """Send JSON logs for the root logger (and uvicorn's loggers) to stdout."""
    global _service_name
    _service_name = service

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(HomeAiJsonFormatter())
    handler.addFilter(ContextFilter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True
    # Our middleware writes the access log with request ids; silence uvicorn's copy.
    logging.getLogger("uvicorn.access").disabled = True


def set_log_context(*, tenant_id: str | None = None, user_id: str | None = None) -> None:
    """Attach the caller's tenant/user to log lines for the rest of this request."""
    if tenant_id is not None:
        tenant_id_var.set(tenant_id)
    if user_id is not None:
        user_id_var.set(user_id)


def get_request_id() -> str | None:
    return request_id_var.get()


def request_id_from_scope(scope: Scope) -> str | None:
    """Request id stored by RequestIdMiddleware (survives after the context var resets)."""
    state = scope.get("state") or {}
    value = state.get(_SCOPE_STATE_KEY) if isinstance(state, dict) else None
    return value or request_id_var.get()


def mask_email(email: str | None) -> str | None:
    """``ruth.smith@example.com`` -> ``r***@example.com``."""
    if not email or "@" not in email:
        return email
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"


def _incoming_request_id(scope: Scope) -> str | None:
    for name, value in scope.get("headers") or []:
        if name.lower() == b"x-request-id":
            candidate = value.decode("latin-1").strip()
            return candidate if _VALID_REQUEST_ID.match(candidate) else None
    return None


class RequestIdMiddleware:
    """Pure ASGI middleware: echo or generate ``X-Request-Id`` and write an access log line.

    Malformed incoming ids (too long, odd characters) are replaced with a fresh UUID so
    they never reach the logs.
    """

    def __init__(self, app: ASGIApp, *, access_log: bool = True):
        self.app = app
        self.access_log = access_log

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _incoming_request_id(scope) or str(uuid.uuid4())
        scope.setdefault("state", {})[_SCOPE_STATE_KEY] = request_id
        tokens = (
            request_id_var.set(request_id),
            tenant_id_var.set(None),
            user_id_var.set(None),
        )
        started = time.perf_counter()
        status_code = 500

        async def send_with_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = [
                    (k, v) for k, v in message.get("headers", []) if k.lower() != b"x-request-id"
                ]
                headers.append((b"x-request-id", request_id.encode("latin-1")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            if self.access_log:
                access_logger.info(
                    "request",
                    extra={
                        "method": scope.get("method"),
                        "path": scope.get("path"),
                        "status": status_code,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    },
                )
            request_id_var.reset(tokens[0])
            tenant_id_var.reset(tokens[1])
            user_id_var.reset(tokens[2])
