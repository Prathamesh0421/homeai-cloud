#!/usr/bin/env python3
"""Dev only: print a JWT for a seeded user or service client (P0-10, docs/03 §6 `make token`).

Tokens come from C4 itself (``POST /auth/login`` for users, ``POST /auth/service-token`` for
clients), so every service accepts them. Standard library only; prints just the token so it can
be captured:

    make token ROLE=iot_staff                    # first seeded user with that role
    make token EMAIL=owner.oak@acme.test
    make token CLIENT=c3-worker                  # scopes from contract 02 §2.3
    TOKEN=$(make -s token ROLE=cloud_staff)

Environment: ``C4_PUBLIC_URL`` (default http://localhost:8004; use http://<host> behind Caddy),
``DEMO_PASSWORD`` (default ``Demo!2026``), ``SERVICE_CLIENT_SECRET_<C2|C3|C4|DEVICE>`` (default the
dev secrets the C4 seed uses).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from seed_ids import USERS

# Contract 02 §2.3: client id -> (scopes, secret env var, dev default secret).
CLIENTS = {
    "c2-alerts": (["clips:playback"], "SERVICE_CLIENT_SECRET_C2", "dev-c2-secret"),
    "c3-worker": (["alerts:evaluate"], "SERVICE_CLIENT_SECRET_C3", "dev-c3-secret"),
    "c3-data": (["alerts:evaluate"], "SERVICE_CLIENT_SECRET_C3", "dev-c3-secret"),
    "c4-dashboard": (
        ["feeds:read", "alerts:read", "records:read"],
        "SERVICE_CLIENT_SECRET_C4",
        "dev-c4-secret",
    ),
    "device-uploader": (["ingest:write"], "SERVICE_CLIENT_SECRET_DEVICE", "dev-device-secret"),
}


def email_for_role(role: str) -> str:
    for email, (_, user_role, _, _) in USERS.items():
        if user_role == role:
            return email
    roles = sorted({r for _, r, _, _ in USERS.values()})
    raise SystemExit(f"no seeded user with role {role!r}; roles: {', '.join(roles)}")


def client_request(client_id: str) -> dict:
    if client_id not in CLIENTS:
        raise SystemExit(f"unknown client {client_id!r}; clients: {', '.join(CLIENTS)}")
    scopes, env_var, default = CLIENTS[client_id]
    return {
        "client_id": client_id,
        "client_secret": os.environ.get(env_var, default),
        "scope": scopes,
    }


def post(url: str, body: dict) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        raise SystemExit(f"C4 answered {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"cannot reach C4 at {url}: {exc.reason}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print a dev JWT from C4.")
    who = parser.add_mutually_exclusive_group(required=True)
    who.add_argument("--role", help="house_owner, iot_staff or cloud_staff")
    who.add_argument("--email", help="a seeded user's email")
    who.add_argument("--client", help="a service client id, e.g. c3-worker")
    parser.add_argument(
        "--c4-url", default=os.environ.get("C4_PUBLIC_URL", "http://localhost:8004")
    )
    args = parser.parse_args(argv)
    base = args.c4_url.rstrip("/")

    if args.client:
        body = post(f"{base}/api/v1/auth/service-token", client_request(args.client))
    else:
        email = args.email or email_for_role(args.role)
        password = os.environ.get("DEMO_PASSWORD", "Demo!2026")
        body = post(f"{base}/api/v1/auth/login", {"email": email, "password": password})
    print(body["data"]["token"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
