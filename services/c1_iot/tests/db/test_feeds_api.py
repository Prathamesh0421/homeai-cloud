"""C1-04/05/08: feeds, config versions and /feeds/stats against Postgres (plan §3.2)."""

from __future__ import annotations

import pytest
from app.models import CameraFeed, House

from tests.factories import (
    HOUSE_A1,
    HOUSE_A2,
    HOUSE_B1,
    ROOM_A1_BATH,
    ROOM_A1_KITCHEN,
    ROOM_B1_KITCHEN,
    STAFF_USER,
    TENANT_A,
    make_feed,
)

FEEDS = "/api/v1/feeds"
CONFIG = {"capture_interval_s": 30, "sensitivity": "medium", "network_label": "hall-ap"}


def new_feed(api, headers, **overrides) -> dict:
    body = {"name": "Hall Mic", "media_kind": "audio", "house_id": HOUSE_A1, "config": CONFIG}
    body.update(overrides)
    resp = api.post(FEEDS, json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


@pytest.fixture
def maple(seeded) -> House:
    return seeded.get(House, HOUSE_A1)


# --- create and read -------------------------------------------------------------------------


def test_create_feed_is_provisioned_disabled_v1(api, staff):
    feed = new_feed(api, staff)
    assert (feed["status"], feed["is_enabled"], feed["config_version"]) == ("provisioned", False, 1)
    assert feed["connectivity_status"] == "unknown"
    assert (feed["house_name"], feed["room_id"], feed["room_name"]) == ("Maple St", None, None)
    assert feed["tenant_id"] == TENANT_A
    assert feed["config"] == CONFIG
    versions = api.get(f"{FEEDS}/{feed['feed_id']}/config-versions", headers=staff).json()["data"]
    assert [(v["version"], v["created_by"]) for v in versions] == [(1, STAFF_USER)]


def test_create_feed_validation(api, staff):
    other_house_room = new = {"name": "X", "media_kind": "audio", "house_id": HOUSE_A2}
    resp = api.post(
        FEEDS, json={**new, "room_id": ROOM_A1_KITCHEN, "config": CONFIG}, headers=staff
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["details"][0]["field"] == "room_id"
    resp = api.post(
        FEEDS, json={**other_house_room, "house_id": HOUSE_B1, "config": CONFIG}, headers=staff
    )
    assert resp.status_code == 422  # another tenant's house is unknown to iot_staff of A
    assert resp.json()["error"]["details"][0]["field"] == "house_id"
    bad_interval = {**CONFIG, "capture_interval_s": 4}
    assert api.post(FEEDS, json={**new, "config": bad_interval}, headers=staff).status_code == 422
    new_feed(api, staff, name="Hall Mic")
    dup = api.post(
        FEEDS,
        json={**new, "house_id": HOUSE_A1, "name": "hall mic", "config": CONFIG},
        headers=staff,
    )
    assert dup.status_code == 422
    assert dup.json()["error"]["details"][0]["field"] == "name"


def test_get_feed_includes_recent_clips(api, staff):
    feed = new_feed(api, staff, room_id=ROOM_A1_KITCHEN)
    body = api.get(f"{FEEDS}/{feed['feed_id']}", headers=staff).json()["data"]
    assert body["recent_clips"] == []
    assert body["room_name"] == "Kitchen"


def test_list_filters_and_scope(api, staff, owner, staff_b, seeded, maple):
    seeded.add_all(
        [
            make_feed(maple, ROOM_A1_KITCHEN, name="Kitchen Mic", is_enabled=True, status="active"),
            make_feed(maple, None, name="Front Cam", media_kind="video"),
        ]
    )
    pine = seeded.get(House, HOUSE_B1)
    seeded.add(make_feed(pine, ROOM_B1_KITCHEN, name="Pine Mic"))
    seeded.flush()

    names = lambda resp: sorted(f["name"] for f in resp.json()["data"])  # noqa: E731
    assert names(api.get(FEEDS, headers=staff)) == ["Front Cam", "Kitchen Mic"]
    assert names(api.get(FEEDS, params={"media_kind": "video"}, headers=staff)) == ["Front Cam"]
    assert names(api.get(FEEDS, params={"is_enabled": True}, headers=staff)) == ["Kitchen Mic"]
    assert names(api.get(FEEDS, params={"status": "active"}, headers=staff)) == ["Kitchen Mic"]
    assert names(api.get(FEEDS, params={"room_id": ROOM_A1_KITCHEN}, headers=staff)) == [
        "Kitchen Mic"
    ]
    assert names(api.get(FEEDS, params={"house_id": HOUSE_A2}, headers=staff)) == []
    assert names(api.get(FEEDS, headers=owner)) == ["Front Cam", "Kitchen Mic"]
    assert names(api.get(FEEDS, headers=staff_b)) == ["Pine Mic"]


def test_owner_is_read_only_and_isolated(api, staff, owner, auth_header):
    feed = new_feed(api, staff)
    fid = feed["feed_id"]
    assert api.get(f"{FEEDS}/{fid}", headers=owner).status_code == 200
    assert api.patch(f"{FEEDS}/{fid}", json={"name": "x"}, headers=owner).status_code == 403
    assert api.put(f"{FEEDS}/{fid}/config", json=CONFIG, headers=owner).status_code == 403
    oak_owner = auth_header(role="house_owner", tenant_id=TENANT_A, house_ids=[HOUSE_A2])
    assert api.get(f"{FEEDS}/{fid}", headers=oak_owner).status_code == 404


def test_other_tenant_feed_is_404(api, staff, staff_b):
    fid = new_feed(api, staff)["feed_id"]
    assert api.get(f"{FEEDS}/{fid}", headers=staff_b).status_code == 404
    assert (
        api.patch(f"{FEEDS}/{fid}/status", json={"is_enabled": False}, headers=staff_b).status_code
        == 404
    )


# --- status, room, archive -------------------------------------------------------------------


def test_enable_needs_room_then_works(api, staff):
    fid = new_feed(api, staff)["feed_id"]
    resp = api.patch(f"{FEEDS}/{fid}/status", json={"is_enabled": True}, headers=staff)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "room_required"

    moved = api.patch(f"{FEEDS}/{fid}", json={"room_id": ROOM_A1_BATH}, headers=staff)
    assert moved.json()["data"]["room_name"] == "Bathroom"
    resp = api.patch(f"{FEEDS}/{fid}/status", json={"is_enabled": True}, headers=staff)
    assert resp.status_code == 200
    assert resp.json()["data"]["is_enabled"] is True

    cleared = api.patch(f"{FEEDS}/{fid}", json={"room_id": None}, headers=staff)
    assert cleared.status_code == 409
    assert cleared.json()["error"]["code"] == "room_required"

    off = api.patch(f"{FEEDS}/{fid}/status", json={"is_enabled": False}, headers=staff)
    assert off.json()["data"]["is_enabled"] is False
    assert api.patch(f"{FEEDS}/{fid}", json={"room_id": None}, headers=staff).status_code == 200


def test_move_to_room_of_other_house_is_422(api, staff):
    fid = new_feed(api, staff, house_id=HOUSE_A2)["feed_id"]
    resp = api.patch(f"{FEEDS}/{fid}", json={"room_id": ROOM_A1_KITCHEN}, headers=staff)
    assert resp.status_code == 422


def test_enabling_feed_in_error_resets_it(api, staff, seeded, maple):
    feed = make_feed(maple, ROOM_A1_KITCHEN, status="error", consecutive_failures=3)
    seeded.add(feed)
    seeded.flush()
    resp = api.patch(f"{FEEDS}/{feed.feed_id}/status", json={"is_enabled": True}, headers=staff)
    assert resp.json()["data"]["status"] == "provisioned"
    seeded.expire_all()
    assert seeded.get(CameraFeed, feed.feed_id).consecutive_failures == 0


def test_archive_hides_feed_and_blocks_changes(api, staff):
    fid = new_feed(api, staff, room_id=ROOM_A1_KITCHEN)["feed_id"]
    api.patch(f"{FEEDS}/{fid}/status", json={"is_enabled": True}, headers=staff)
    assert api.delete(f"{FEEDS}/{fid}", headers=staff).status_code == 204
    assert api.delete(f"{FEEDS}/{fid}", headers=staff).status_code == 204  # idempotent
    assert api.get(FEEDS, headers=staff).json()["data"] == []
    archived = api.get(FEEDS, params={"include_archived": True}, headers=staff).json()["data"]
    assert archived[0]["is_enabled"] is False
    assert archived[0]["archived_at"].endswith("Z")
    assert api.patch(f"{FEEDS}/{fid}", json={"name": "x"}, headers=staff).status_code == 404
    # The name can be reused by a new feed.
    new_feed(api, staff, name=archived[0]["name"])


# --- config versions (C1-05) -----------------------------------------------------------------


def test_config_versions_put_and_restore(api, staff):
    fid = new_feed(api, staff)["feed_id"]
    v2 = api.put(f"{FEEDS}/{fid}/config", json={**CONFIG, "capture_interval_s": 10}, headers=staff)
    assert v2.status_code == 200
    assert v2.json()["data"] == {
        "config_version": 2,
        "config": {**CONFIG, "capture_interval_s": 10},
    }

    v3 = api.post(f"{FEEDS}/{fid}/config-versions/1/restore", headers=staff)
    assert v3.json()["data"] == {"config_version": 3, "config": CONFIG}

    versions = api.get(f"{FEEDS}/{fid}/config-versions", headers=staff).json()["data"]
    assert [(v["version"], v["capture_interval_s"]) for v in versions] == [
        (3, 30),
        (2, 10),
        (1, 30),
    ]
    feed = api.get(f"{FEEDS}/{fid}", headers=staff).json()["data"]
    assert (feed["config_version"], feed["config"]["capture_interval_s"]) == (3, 30)


def test_restore_unknown_version_is_404(api, staff):
    fid = new_feed(api, staff)["feed_id"]
    resp = api.post(f"{FEEDS}/{fid}/config-versions/9/restore", headers=staff)
    assert resp.status_code == 404


def test_bad_config_is_422(api, staff):
    fid = new_feed(api, staff)["feed_id"]
    resp = api.put(f"{FEEDS}/{fid}/config", json={**CONFIG, "sensitivity": "max"}, headers=staff)
    assert resp.status_code == 422
    assert resp.json()["error"]["details"][0]["field"] == "sensitivity"


# --- stats (contract §4.6) -------------------------------------------------------------------


def test_feed_stats_shape_and_scope(api, staff, ops, owner, auth_header, seeded, maple):
    seeded.add_all(
        [
            make_feed(
                maple,
                ROOM_A1_KITCHEN,
                is_enabled=True,
                status="active",
                connectivity_status="online",
            ),
            make_feed(
                maple,
                ROOM_A1_BATH,
                is_enabled=True,
                status="inactive",
                connectivity_status="offline",
            ),
            make_feed(maple, None),
        ]
    )
    pine = seeded.get(House, HOUSE_B1)
    seeded.add(make_feed(pine, ROOM_B1_KITCHEN, status="error"))
    seeded.flush()

    acme = api.get(f"{FEEDS}/stats", headers=staff).json()["data"]
    assert acme == {
        "houses": 2,
        "total": 3,
        "by_status": {"provisioned": 1, "active": 1, "inactive": 1, "error": 0},
        "online": 1,
    }
    everything = api.get(f"{FEEDS}/stats", headers=ops).json()["data"]
    assert (everything["houses"], everything["total"], everything["by_status"]["error"]) == (
        3,
        4,
        1,
    )

    c4 = auth_header(service_scopes=["feeds:read"])
    one_house = api.get(f"{FEEDS}/stats", params={"house_id": HOUSE_B1}, headers=c4).json()["data"]
    assert (one_house["houses"], one_house["total"]) == (1, 1)
    by_tenant = api.get(f"{FEEDS}/stats", params={"tenant_id": TENANT_A}, headers=c4).json()["data"]
    assert by_tenant["total"] == 3

    assert api.get(f"{FEEDS}/stats", headers=owner).status_code == 403
    wrong_scope = auth_header(service_scopes=["alerts:read"])
    assert api.get(f"{FEEDS}/stats", headers=wrong_scope).status_code == 403
