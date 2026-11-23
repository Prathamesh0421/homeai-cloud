"""I-7 (docs/05 §4): logout → C1/C2/C3 reject the old JWT within the revocation cache window.

Depends on S-6 (``homeai_common`` polls ``GET /auth/revoked``, default TTL 60 s). Set
``REVOCATION_CACHE_TTL_SECONDS`` lower on the stack to speed this up; the test waits ≤ 65 s.
"""

from __future__ import annotations

import time

import pytest

pytestmark = pytest.mark.integration

OWNER = "owner.maple@acme.test"
# User-scoped GETs that every role can hit through the gateway.
PROBE_PATHS = (
    ("c1", "/api/v1/feeds"),
    ("c2", "/api/v1/alerts?page_size=1"),
    ("c3", "/api/v1/records/clips?page_size=1"),
)


def test_i7_logout_revokes_token_on_c1_c2_c3(stack):
    token = stack.user_token(OWNER)
    # Prove the token works before logout.
    for _name, path in PROBE_PATHS:
        r = stack.request("GET", path, token)
        assert r.status_code == 200, f"{path} before logout: {r.status_code} {r.text[:200]}"

    logout = stack.request("POST", "/api/v1/auth/logout", token)
    assert logout.status_code == 204, logout.text
    # Drop the cached login so later helpers re-authenticate with a fresh token.
    stack._tokens.pop(OWNER, None)

    # C4 itself rejects immediately via the denylist on /auth/me.
    me = stack.request("GET", "/api/v1/auth/me", token)
    assert me.status_code == 401, me.text
    assert me.json()["error"]["code"] == "token_revoked"

    # Other services: wait out the revocation cache (contracts §2.4: 60 s).
    deadline = time.monotonic() + 65
    last: dict[str, int] = {}
    while time.monotonic() < deadline:
        last = {}
        all_revoked = True
        for name, path in PROBE_PATHS:
            r = stack.request("GET", path, token)
            last[name] = r.status_code
            if r.status_code != 401:
                all_revoked = False
        if all_revoked:
            break
        time.sleep(2)
    else:
        pytest.fail(f"old JWT still accepted after 65 s (need S-6 cache on C1-C3): {last}")

    for name, path in PROBE_PATHS:
        r = stack.request("GET", path, token)
        assert r.status_code == 401, f"{name} {path}: {r.status_code} {r.text[:200]}"
        code = r.json().get("error", {}).get("code")
        assert code in ("token_revoked", "unauthorized"), (name, code, r.text[:200])
