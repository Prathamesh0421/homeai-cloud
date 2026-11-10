"""P0-10 scripts (repo root ``scripts/``): master seed plan and dev token requests."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[4] / "scripts"


def _load(name: str):
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(f"p0_{name}", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look the module up while the class is built
    spec.loader.exec_module(module)
    return module


seed = _load("seed")
mint = _load("mint_token")


def test_seed_order_is_c4_c1_c2():
    assert [s.code for s in seed.STEPS] == ["c4", "c1", "c2"]


def test_plan_skips_services_that_are_not_running():
    to_run, skipped = seed.plan(None, {"c4-dashboard", "c2-alerts"})
    assert [s.code for s in to_run] == ["c4", "c2"]
    assert [s.code for s in skipped] == ["c1"]
    to_run, _ = seed.plan({"c1"}, {"c4-dashboard", "c1-iot"})
    assert [s.code for s in to_run] == ["c1"]


def test_seed_commands_mount_repo_as_one_argument_even_with_spaces():
    step = seed.STEPS[1]
    migrate, run = seed.commands(["docker", "compose"], step, Path("/a dir/repo"))
    assert migrate == ["docker", "compose", "exec", "-T", "c1-iot", "alembic", "upgrade", "head"]
    assert "/a dir/repo:/workspace:ro" in run
    assert run[-4:] == ["c1-iot", "python", "-m", "app.seed"]


def test_token_role_and_client_mapping(monkeypatch):
    assert mint.email_for_role("iot_staff") == "iot@acme.test"
    assert mint.email_for_role("cloud_staff") == "ops@homeai.test"
    with pytest.raises(SystemExit):
        mint.email_for_role("admin")
    monkeypatch.delenv("SERVICE_CLIENT_SECRET_DEVICE", raising=False)
    assert mint.client_request("device-uploader") == {
        "client_id": "device-uploader",
        "client_secret": "dev-device-secret",
        "scope": ["ingest:write"],
    }
    assert mint.client_request("c4-dashboard")["scope"] == [
        "feeds:read",
        "alerts:read",
        "records:read",
    ]
    with pytest.raises(SystemExit):
        mint.client_request("nobody")
