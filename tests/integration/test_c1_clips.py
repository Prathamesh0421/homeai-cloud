"""I-1 (C1 -> C3) and I-4 (C2 -> C1 clip) from docs/05 §4, with a real clip and YAMNet.

I-1: a clip ingested by C1 is picked up by C3's worker, analysed, and C1's Clip Library shows the
result. I-4: the alert raised from that clip plays back the very bytes C1 stored, both for the
signed-in owner (C1 presigned URL) and on an emergency contact's public alert view (C2 asks C1
with its service token). The alert is resolved and Maple's settings restored by ``maple``.
"""

from __future__ import annotations

import time

import httpx
import pytest
import seed_ids
from stack import DEMO_CLIPS, StackError
from test_c2_detections import maple, resend  # noqa: F401  (maple is a fixture)

pytestmark = pytest.mark.integration

MAPLE = seed_ids.HOUSES["maple"][0]
FEED = "maple_kitchen_mic"
FEED_ID = seed_ids.FEEDS[FEED][0]
KITCHEN = seed_ids.room_id("maple", "Kitchen")
OWNER = "owner.maple@acme.test"
CLIP = "glass_break.wav"


def download(url: str) -> bytes:
    r = httpx.get(url, timeout=15, follow_redirects=True)
    assert r.status_code == 200, f"{url[:120]}... -> {r.status_code}: {r.text[:200]}"
    return r.content


def test_i1_c1_clip_is_analysed_by_c3(stack):
    owner = stack.user_token(OWNER)
    started = time.monotonic()
    media_id = stack.upload_clip(FEED, CLIP)

    detection = stack.wait_for_detection(media_id, owner, within=30)
    print(f"{CLIP}: {detection['top_label']} {detection['top_confidence']:.3f}")
    assert time.monotonic() - started <= 30
    assert detection["top_label"] == "glass_break", detection
    assert detection["media_id"] == media_id
    assert (detection["house_id"], detection["room_id"]) == (MAPLE, KITCHEN)

    # C1's own view of the clip shows C3's result (C1 reads ai_detections).
    clip = stack.call("GET", f"/api/v1/clips/{media_id}", owner)["data"]
    assert clip["status"] == "analyzed", clip
    assert clip["top_label"] == "glass_break", clip
    assert (clip["feed_id"], clip["house_id"]) == (FEED_ID, MAPLE)


def test_i4_alert_plays_back_the_clip_c1_stored(stack, maple):  # noqa: F811
    owner = stack.user_token(OWNER)
    stored = (DEMO_CLIPS / CLIP).read_bytes()
    media_id = stack.upload_clip(FEED, CLIP)
    detection = stack.wait_for_detection(media_id, owner)
    if detection["top_label"] != "glass_break":
        pytest.fail(f"YAMNet labelled {CLIP} {detection['top_label']}: {detection}")

    # C3's handoff raised the alert; evaluating the detection again returns its id.
    decision = resend(stack, detection, maple)
    assert decision["decision"] == "alert" and decision["duplicate"] is True, decision
    alert = stack.call("GET", f"/api/v1/alerts/{decision['alert_id']}", owner)["data"]
    assert alert["media_id"] == media_id, alert

    # Owner: the browser asks C1 for the alert's clip (Alert Detail -> Play recording).
    playback = stack.call("GET", f"/api/v1/clips/{media_id}/playback-url", owner)["data"]
    assert download(playback["url"]) == stored

    # Emergency contact: the signed link's view carries C1's URL, fetched by C2.
    links = [n["view_link"] for n in alert["notifications"] if n.get("view_link")]
    if not links:
        raise StackError("no notification with a view link: is DEMO_MODE=1 and Maple seeded?")
    token = links[0].rstrip("/").split("/")[-1]
    view = httpx.get(f"{stack.base_url.rstrip('/')}/api/v1/alert-view/{token}", timeout=10)
    assert view.status_code == 200, view.text
    clip_url = view.json()["data"]["clip_url"]
    assert clip_url, "public alert view has no clip_url (C1 did not answer C2 within 2 s?)"
    assert download(clip_url) == stored
