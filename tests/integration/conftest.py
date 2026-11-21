"""Integration tests against a running, seeded stack (docs/05 §4). Not part of CI.

    HOMEAI_API_URL=http://localhost:8080 pytest tests/integration -m integration

Needs: C1 + C3 (YAMNet) + C2 + C4 behind the gateway, ``make seed``, ``demo_clips/`` fetched, and
C3 handing detections to C2 (``HANDOFF_MODE=call``; for ``make up`` add
``-f tests/integration/compose.handoff.yml``). Skipped when ``HOMEAI_API_URL`` is unset.
``DEMO_PASSWORD`` and ``SERVICE_CLIENT_SECRET_C3``/``_DEVICE`` default to the dev values.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from stack import Stack


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "integration: needs the running stack (HOMEAI_API_URL)")


@pytest.fixture(scope="session")
def stack():
    s = Stack.from_env()
    if s is None:
        pytest.skip("HOMEAI_API_URL not set: integration tests need the running stack")
    yield s
    s.close()
