"""I-2 (C3 -> C2) and I-3 (C4 settings -> C2) from docs/05 §4, with real clips and YAMNet.

Each test uploads demo clips to Maple's Kitchen Mic, waits for C3 to classify them and hand
them to C2, then checks C2's decision. YAMNet's confidence for a clip is whatever the model
says, so expected decisions are worked out from the stored detection and the rule's threshold
rather than hard-coded. Maple's settings and contact order are restored afterwards; the alerts
raised are resolved.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
import seed_ids

pytestmark = pytest.mark.integration

MAPLE = seed_ids.HOUSES["maple"][0]
MAPLE_TZ = seed_ids.HOUSES["maple"][3]
ACME = seed_ids.TENANTS["acme"]
FEED = "maple_kitchen_mic"
OWNER = "owner.maple@acme.test"
OPS = "ops@homeai.test"
ALL_SERVICES = ["fire_safety", "distress", "intrusion", "fall", "wellness", "presence", "pet"]
SENSITIVITY_OFFSET = {"low": 0.10, "medium": 0.0, "high": -0.10}


def threshold(stack, alert_type_code: str, sensitivity: str) -> float:
    """C2's effective threshold for Maple: its whole-house rule, else the tenant default."""
    rules = stack.call(
        "GET",
        "/api/v1/alert-rules",
        stack.user_token(OPS),
        params={"tenant_id": ACME, "alert_type_code": alert_type_code, "is_enabled": True},
    )["data"]
    house = [r for r in rules if r["house_id"] == MAPLE and r["room_id"] is None]
    default = [r for r in rules if r["scope"] == "tenant_default"]
    rule = (house or default)[0]
    shifted = rule["min_confidence"] + SENSITIVITY_OFFSET[sensitivity]
    return round(min(max(shifted, 0.05), 0.95), 2)


def put_settings(stack, *, sensitivity="medium", quiet: tuple[str, str] | None = None) -> None:
    stack.call(
        "PUT",
        f"/api/v1/houses/{MAPLE}/settings",
        stack.user_token(OWNER),
        json={
            "enabled_services": ALL_SERVICES,
            "quiet_start": quiet[0] if quiet else None,
            "quiet_end": quiet[1] if quiet else None,
            "sensitivity": sensitivity,
        },
    )


def quiet_window_around_now() -> tuple[str, str]:
    now = datetime.now(ZoneInfo(MAPLE_TZ))
    return (
        (now - timedelta(hours=1)).strftime("%H:%M"),
        (now + timedelta(hours=1)).strftime("%H:%M"),
    )


def contacts(stack) -> list[str]:
    rows = stack.call("GET", f"/api/v1/houses/{MAPLE}/emergency-contacts", stack.user_token(OWNER))[
        "data"
    ]
    return [c["contact_id"] for c in sorted(rows, key=lambda c: c["priority"])]


def reorder(stack, contact_ids: list[str]) -> None:
    stack.call(
        "PUT",
        f"/api/v1/houses/{MAPLE}/emergency-contacts/order",
        stack.user_token(OWNER),
        json={"contact_ids": contact_ids},
    )


def alert(stack, alert_id: str) -> dict:
    return stack.call("GET", f"/api/v1/alerts/{alert_id}", stack.user_token(OWNER))["data"]


def close(stack, alert_id: str) -> None:
    for action in ("acknowledge", "resolve"):
        stack.call("POST", f"/api/v1/alerts/{alert_id}/{action}", stack.user_token(OWNER), json={})


def detect(stack, clip: str, label: str) -> dict:
    detection = stack.wait_for_detection(stack.upload_clip(FEED, clip), stack.user_token(OPS))
    if detection["top_label"] != label:
        pytest.fail(f"YAMNet labelled {clip} {detection['top_label']}, not {label}: {detection}")
    return detection


def resend(stack, detection: dict) -> dict:
    r = stack.evaluate(detection)
    assert r.status_code == 200, r.text
    return r.json()["data"]


@pytest.fixture
def maple(stack):
    """Maple with every service on, no quiet hours, sensitivity medium; restored afterwards."""
    before = stack.call("GET", f"/api/v1/houses/{MAPLE}/settings", stack.user_token(OWNER))["data"]
    order = contacts(stack)
    raised: list[str] = []
    put_settings(stack)
    yield raised
    for alert_id in raised:
        if alert(stack, alert_id)["status"] in ("open", "acknowledged"):
            close(stack, alert_id)
    reorder(stack, order)
    quiet = (before["quiet_start"], before["quiet_end"]) if before["quiet_start"] else None
    stack.call(
        "PUT",
        f"/api/v1/houses/{MAPLE}/settings",
        stack.user_token(OWNER),
        json={
            "enabled_services": before["enabled_services"],
            "quiet_start": quiet[0] if quiet else None,
            "quiet_end": quiet[1] if quiet else None,
            "sensitivity": before["sensitivity"],
        },
    )


def test_i2_detection_raises_exactly_one_alert(stack, maple):
    started = datetime.now(UTC)
    detection = detect(stack, "glass_break.wav", "glass_break")
    assert detection["top_confidence"] >= threshold(stack, "intrusion", "medium"), detection

    # C3's handoff already raised it: evaluating the same detection again is a duplicate.
    again = resend(stack, detection)
    assert again["decision"] == "alert" and again["duplicate"] is True, again
    maple.append(again["alert_id"])
    got = alert(stack, again["alert_id"])
    assert (got["alert_type_code"], got["severity"], got["status"]) == ("intrusion", "high", "open")
    assert (got["detection_id"], got["media_id"]) == (detection["id"], detection["media_id"])
    assert got["evidence"]["detection_available"] is True

    # Exactly one alert for this detection: one new intrusion alert at Maple since the upload.
    rows = stack.call(
        "GET",
        "/api/v1/alerts",
        stack.user_token(OWNER),
        params={"house_id": MAPLE, "alert_type_code": "intrusion", "from": started.isoformat()},
    )["data"]
    assert [r["alert_id"] for r in rows] == [again["alert_id"]]


def test_i3_quiet_hours_sensitivity_and_contact_order(stack, maple):
    # Contacts reversed, so the email order must follow the new priorities, not the seed's.
    order = list(reversed(contacts(stack)))
    reorder(stack, order)
    put_settings(stack, quiet=quiet_window_around_now())

    # Cough (wellness_cough, low) is held in quiet hours, or is under the threshold anyway.
    cough = detect(stack, "cough.wav", "cough")
    medium = threshold(stack, "wellness_cough", "medium")
    held = resend(stack, cough)
    expected = "quiet_hours" if cough["top_confidence"] >= medium else "below_threshold"
    assert (held["decision"], held["reason"]) == ("no_alert", expected), (cough, held)

    # Glass break (intrusion, high) goes through quiet hours.
    glass = detect(stack, "glass_break.wav", "glass_break")
    assert glass["top_confidence"] >= medium, glass
    raised = resend(stack, glass)
    assert raised["decision"] == "alert" and raised["duplicate"] is True, raised
    maple.append(raised["alert_id"])
    got = alert(stack, raised["alert_id"])
    assert got["severity"] == "high"
    emails = sorted(
        (n for n in got["notifications"] if n["channel"] == "email"), key=lambda n: n["priority"]
    )
    assert [n["contact_id"] for n in emails] == order

    # Outside quiet hours with sensitivity high (threshold -0.10) the same cough is re-judged.
    put_settings(stack, sensitivity="high")
    high = threshold(stack, "wellness_cough", "high")
    rejudged = resend(stack, cough)
    if cough["top_confidence"] >= high:
        assert (rejudged["decision"], rejudged["severity"]) == ("alert", "low"), rejudged
        assert rejudged["duplicate"] is False
        maple.append(rejudged["alert_id"])
    else:
        assert (rejudged["decision"], rejudged["reason"]) == ("no_alert", "below_threshold")
