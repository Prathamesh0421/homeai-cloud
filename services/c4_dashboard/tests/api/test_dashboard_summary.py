"""API test: /dashboard/summary reads upstream stats with C4's own service token (I-5)."""

from __future__ import annotations

import uuid

import bcrypt
import jwt
from app.models.orm import ServiceClient
from app.services import stats_aggregator
from app.services.service_token import reset_stats_token_provider

from tests.conftest import skip_no_postgres


@skip_no_postgres
def test_owner_summary_calls_upstreams_as_c4_dashboard(
    client, db_session, issuer, settings, monkeypatch
):
    db_session.add(
        ServiceClient(
            client_id="c4-dashboard",
            secret_hash=bcrypt.hashpw(b"dev-c4-secret", bcrypt.gensalt()).decode(),
            scopes=["feeds:read", "alerts:read", "records:read"],
        )
    )
    db_session.commit()

    import app.deps as deps_mod

    settings.service_client_secret = "dev-c4-secret"
    monkeypatch.setattr(deps_mod, "get_jwt_issuer", lambda *_a, **_k: issuer)
    reset_stats_token_provider()

    seen: list[dict] = []

    def capture(result):
        def fn(*_a, **k):
            seen.append(k)
            return result

        return fn

    monkeypatch.setattr(
        stats_aggregator.c1_client,
        "fetch_feeds_stats",
        capture({"houses": 1, "total": 2, "online": 1, "by_status": {"active": 2}}),
    )
    monkeypatch.setattr(stats_aggregator.c2_client, "fetch_alerts_stats", capture([]))
    monkeypatch.setattr(stats_aggregator.c2_client, "fetch_recent_alerts", capture([]))
    monkeypatch.setattr(stats_aggregator.c2_client, "fetch_open_alert_count", capture(0))
    monkeypatch.setattr(stats_aggregator.c3_client, "fetch_detections_stats", capture(([], 0)))

    tenant_id, house_id = str(uuid.uuid4()), str(uuid.uuid4())
    user_token, _jti, _ttl = issuer.issue_user_token(
        user_id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        role="house_owner",
        house_ids=[house_id],
        email="owner@example.test",
    )
    try:
        resp = client.get(
            "/api/v1/dashboard/summary", headers={"Authorization": f"Bearer {user_token}"}
        )
    finally:
        reset_stats_token_provider()

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["meta"]["unavailable"] == []
    assert body["data"]["kpis"]["feeds_total"] == 2
    assert len(seen) == 6

    tokens = {k["bearer_token"] for k in seen}
    assert len(tokens) == 1, "one cached service token for all upstreams"
    (svc,) = tokens
    assert svc != user_token
    claims = jwt.decode(svc, options={"verify_signature": False})
    assert claims["typ"] == "service"
    assert claims["sub"] == "c4-dashboard"
    assert set(claims["scope"]) == {"feeds:read", "alerts:read", "records:read"}
    for k in seen:
        assert k["tenant_id"] == tenant_id
        assert k["house_id"] == house_id
