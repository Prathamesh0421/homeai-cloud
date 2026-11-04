"""C3 inference worker entrypoint (``python -m app.worker``).

Phase 2 is a skeleton: it configures logging, derives a stable ``worker_id``,
logs that it started and idles. The claim/classify/retry/heartbeat loop lands in
C3-06 (Phase 5).
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import time
from types import FrameType

from homeai_common.logging import configure_logging

from app.settings import SERVICE_NAME, get_settings

logger = logging.getLogger("c3.worker")

_stop = False


def _handle_stop(signum: int, _frame: FrameType | None) -> None:
    global _stop
    _stop = True
    logger.info("C3 worker stopping", extra={"signal": signum})


def worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


def main() -> None:
    settings = get_settings()
    configure_logging(f"{SERVICE_NAME}-worker", settings.log_level)

    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    wid = worker_id()
    logger.info("C3 worker started", extra={"worker_id": wid})

    # Idle loop until the claim/classify pipeline is wired up in Phase 5.
    while not _stop:
        time.sleep(settings.worker_sleep)


if __name__ == "__main__":
    main()
