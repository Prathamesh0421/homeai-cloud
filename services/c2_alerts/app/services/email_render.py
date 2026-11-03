"""Alert email text (C2 plan §4.3).

SNS email subjects must be ASCII, one line and under 100 characters, so the plan's
``[HomeAI] CRITICAL Smoke alarm — Maple St`` is sent with ``-`` instead of the em dash.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SUBJECT_MAX = 99
FALLBACK_SUBJECT = "[HomeAI] alert"


@dataclass(frozen=True)
class EmailFacts:
    severity: str
    alert_type_name: str
    house_name: str | None
    room_name: str | None
    house_timezone: str | None
    triggered_at: datetime
    top_label: str
    top_confidence: float
    contact_name: str
    link: str
    link_expires_at: datetime


@dataclass(frozen=True)
class EmailMessage:
    subject: str
    body: str


def sns_subject(text: str) -> str:
    """ASCII, single line, < 100 chars; non-ASCII letters lose their accents."""
    text = text.replace("\u2014", "-").replace("\u2013", "-")  # em / en dash
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    one_line = re.sub(r"\s+", " ", ascii_text).strip()
    if not re.search(r"[A-Za-z0-9]", one_line):
        return FALLBACK_SUBJECT
    return one_line[:SUBJECT_MAX].rstrip()


def _local(when: datetime, timezone: str | None) -> str | None:
    if not timezone:
        return None
    try:
        return when.astimezone(ZoneInfo(timezone)).strftime("%Y-%m-%d %H:%M %Z")
    except (ZoneInfoNotFoundError, ValueError):
        return None


def _utc(when: datetime) -> str:
    return when.strftime("%Y-%m-%d %H:%M UTC")


def render_email(f: EmailFacts) -> EmailMessage:
    title = f"{f.severity.upper()} {f.alert_type_name}"
    subject = f"[HomeAI] {title} - {f.house_name}" if f.house_name else f"[HomeAI] {title}"

    local = _local(f.triggered_at, f.house_timezone)
    when = f"{local} ({_utc(f.triggered_at)})" if local else _utc(f.triggered_at)
    expires = _local(f.link_expires_at, f.house_timezone) or _utc(f.link_expires_at)
    label = f.top_label.replace("_", " ")

    lines = [
        f"Hi {f.contact_name}," if f.contact_name else "Hello,",
        "",
        f"HomeAI raised a {title} alert at {f.house_name or 'your home'}.",
        "",
        f"Room: {f.room_name or 'not recorded'}",
        f"When: {when}",
        f"Detected: {label} ({f.top_confidence:.0%} confidence)",
        "",
        f"See the alert and what was detected (no login needed): {f.link}",
        f"This link works until {expires}.",
        "",
        "If someone is in danger, call 911.",
        "",
        "You are receiving this because you are an emergency contact for this home.",
    ]
    return EmailMessage(subject=sns_subject(subject), body="\n".join(lines))
