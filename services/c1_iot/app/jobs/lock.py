"""Fixed 64-bit Postgres advisory-lock keys for C1 ("C1" + slot number).

C2 uses 0x4332…, C3 0x4333…, C4 0x4334…, so the keys never collide in the shared database.
"""

from __future__ import annotations

# Slot 0: Alembic. Every copy runs `alembic upgrade head` on start (alembic/env.py, S-3).
MIGRATION_LOCK = 0x4331_0000_0000
# Slot 1: ConnectivityMonitor runs (app/jobs/connectivity_monitor.py).
CONNECTIVITY_LOCK = 0x4331_0000_0001
