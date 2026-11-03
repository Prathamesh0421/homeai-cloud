"""Alert email rendering (C2 plan §4.3) incl. SNS subject rules."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.services.email_render import EmailFacts, render_email, sns_subject

TRIGGERED = datetime(2026, 10, 25, 6, 10, tzinfo=UTC)  # 23:10 PDT on the 24th
EXPIRES = datetime(2026, 10, 26, 6, 10, tzinfo=UTC)


def facts(**overrides) -> EmailFacts:
    base = {
        "severity": "critical",
        "alert_type_name": "Smoke alarm",
        "house_name": "Maple St",
        "room_name": "Kitchen",
        "house_timezone": "America/Los_Angeles",
        "triggered_at": TRIGGERED,
        "top_label": "smoke_alarm",
        "top_confidence": 0.873,
        "contact_name": "Dana",
        "link": "https://homeai.example/alert-view/tok",
        "link_expires_at": EXPIRES,
    }
    base.update(overrides)
    return EmailFacts(**base)


def test_subject():
    assert render_email(facts()).subject == "[HomeAI] CRITICAL Smoke alarm - Maple St"


def test_body_has_everything_the_plan_lists():
    body = render_email(facts()).body
    assert "Hi Dana," in body
    assert "Room: Kitchen" in body
    assert "Maple St" in body
    assert "2026-10-24 23:10 PDT" in body  # house-local time
    assert "2026-10-25 06:10 UTC" in body
    assert "smoke alarm (87% confidence)" in body
    assert "https://homeai.example/alert-view/tok" in body
    assert "2026-10-25 23:10 PDT" in body  # link expiry, house-local
    assert "If someone is in danger, call 911." in body


def test_missing_names_fall_back():
    body = render_email(facts(house_name=None, room_name=None, contact_name="")).body
    assert "Room: not recorded" in body
    assert "your home" in body
    assert body.startswith("Hello,")
    assert render_email(facts(house_name=None)).subject == "[HomeAI] CRITICAL Smoke alarm"


def test_unknown_timezone_shows_utc_only():
    body = render_email(facts(house_timezone="Nowhere/Here")).body
    assert "2026-10-25 06:10 UTC" in body


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("[HomeAI] HIGH Glass break — Café Ñandú", "[HomeAI] HIGH Glass break - Cafe Nandu"),
        ("line\nbreak\ttab", "line break tab"),
        ("日本の家", "[HomeAI] alert"),  # nothing ASCII left
        ("x" * 150, "x" * 99),
        ("   ", "[HomeAI] alert"),
    ],
)
def test_sns_subject_is_ascii_one_line_under_100(raw, expected):
    got = sns_subject(raw)
    assert got == expected
    assert got.isascii() and "\n" not in got and len(got) < 100
