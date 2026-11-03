"""C2 vocabularies from docs/02_CONTRACTS.md §3 (use these exact strings)."""

from __future__ import annotations

SEVERITIES: tuple[str, ...] = ("critical", "high", "medium", "low")
# Higher rank = more severe; used to order rules and pick the strongest match.
SEVERITY_RANK: dict[str, int] = {"critical": 4, "high": 3, "medium": 2, "low": 1}

# C4 house service codes; a house with no settings row has all of them enabled.
SERVICE_CODES: tuple[str, ...] = (
    "fire_safety",
    "distress",
    "intrusion",
    "fall",
    "wellness",
    "presence",
    "pet",
)
SENSITIVITIES: tuple[str, ...] = ("low", "medium", "high")

CATEGORIES: tuple[str, ...] = ("emergency", "safety", "security", "wellness", "system")

ALERT_STATUSES: tuple[str, ...] = ("open", "acknowledged", "resolved", "false_positive")

HOME_LABELS: tuple[str, ...] = (
    "smoke_alarm",
    "distress_sound",
    "glass_break",
    "fall_indicator",
    "cough",
    "speech",
    "dog",
)

NOTIFICATION_CHANNELS: tuple[str, ...] = ("in_app", "email")
NOTIFICATION_STATUSES: tuple[str, ...] = ("queued", "sent", "failed")

SYSTEM_ACTOR = "system"
