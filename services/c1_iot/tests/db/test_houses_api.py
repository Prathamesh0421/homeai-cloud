"""C1-03: houses and rooms API against Postgres (C1 plan §3.1, scope rules §4.3)."""

from __future__ import annotations

from tests.factories import (
    HOUSE_A1,
    HOUSE_A2,
    HOUSE_B1,
    ROOM_A1_BATH,
    ROOM_A1_KITCHEN,
    ROOM_B1_KITCHEN,
    TENANT_A,
    TENANT_B,
    make_feed,
)

HOUSES = "/api/v1/houses"


def names(resp) -> list[str]:
    return [h["name"] for h in resp.json()["data"]]


# --- list and get ---------------------------------------------------------------------------


def test_staff_lists_own_tenant_houses_with_counts(api, staff):
    resp = api.get(HOUSES, headers=staff)
    assert resp.status_code == 200
    assert names(resp) == ["Maple St", "Oak Ave"]
    assert resp.json()["meta"] == {"page": 1, "page_size": 25, "total": 2}
    maple = resp.json()["data"][0]
    assert maple["room_count"] == 2
    assert maple["feed_count"] == 0
    assert maple["created_at"].endswith("Z")


def test_name_filter(api, staff):
    assert names(api.get(HOUSES, params={"q": "oak"}, headers=staff)) == ["Oak Ave"]


def test_cloud_staff_sees_all_tenants_or_filters_one(api, ops):
    assert names(api.get(HOUSES, headers=ops)) == ["Maple St", "Oak Ave", "Pine Rd"]
    assert names(api.get(HOUSES, params={"tenant_id": TENANT_B}, headers=ops)) == ["Pine Rd"]


def test_owner_sees_only_own_house(api, owner):
    assert names(api.get(HOUSES, headers=owner)) == ["Maple St"]
    assert api.get(f"{HOUSES}/{HOUSE_A1}", headers=owner).status_code == 200
    resp = api.get(f"{HOUSES}/{HOUSE_A2}", headers=owner)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_other_tenant_house_is_404(api, staff_b):
    assert api.get(f"{HOUSES}/{HOUSE_A1}", headers=staff_b).status_code == 404
    assert names(api.get(HOUSES, headers=staff_b)) == ["Pine Rd"]


def test_get_house_counts_rooms_and_feeds(api, staff, seeded):
    from app.models import House

    maple = seeded.get(House, HOUSE_A1)
    seeded.add(make_feed(maple, ROOM_A1_KITCHEN))
    seeded.flush()
    body = api.get(f"{HOUSES}/{HOUSE_A1}", headers=staff).json()["data"]
    assert (body["room_count"], body["feed_count"]) == (2, 1)


# --- create, update, delete ------------------------------------------------------------------


def test_staff_creates_house_in_own_tenant(api, staff):
    resp = api.post(
        HOUSES,
        json={"name": "Elm Ct", "timezone": "America/Chicago", "address": "1 Elm Ct"},
        headers=staff,
    )
    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["tenant_id"] == TENANT_A
    assert body["timezone"] == "America/Chicago"
    assert "Elm Ct" in names(api.get(HOUSES, headers=staff))


def test_bad_timezone_is_422_on_field(api, staff):
    resp = api.post(HOUSES, json={"name": "Elm Ct", "timezone": "Mars/Base"}, headers=staff)
    assert resp.status_code == 422
    assert resp.json()["error"]["details"][0]["field"] == "timezone"


def test_duplicate_name_in_tenant_is_422_on_name(api, staff, staff_b):
    resp = api.post(HOUSES, json={"name": "maple st", "timezone": "UTC"}, headers=staff)
    assert resp.status_code == 422
    assert resp.json()["error"]["details"] == [
        {"field": "name", "issue": "a house with this name already exists in the tenant"}
    ]
    # Another tenant may use the same name.
    assert (
        api.post(HOUSES, json={"name": "Maple St", "timezone": "UTC"}, headers=staff_b).status_code
        == 201
    )


def test_cloud_staff_must_name_tenant(api, ops):
    resp = api.post(HOUSES, json={"name": "Birch", "timezone": "UTC"}, headers=ops)
    assert resp.status_code == 422
    assert resp.json()["error"]["details"][0]["field"] == "tenant_id"
    resp = api.post(
        HOUSES, json={"name": "Birch", "timezone": "UTC", "tenant_id": TENANT_B}, headers=ops
    )
    assert resp.status_code == 201
    assert resp.json()["data"]["tenant_id"] == TENANT_B


def test_house_id_only_in_demo_mode(api, staff, settings):
    fixed = "22222222-0000-0000-0000-0000000000a9"
    body = {"name": "Seeded", "timezone": "UTC", "house_id": fixed}
    resp = api.post(HOUSES, json=body, headers=staff)
    assert resp.status_code == 422
    assert resp.json()["error"]["details"][0]["field"] == "house_id"

    settings.demo_mode = True
    resp = api.post(HOUSES, json=body, headers=staff)
    assert resp.status_code == 201
    assert resp.json()["data"]["house_id"] == fixed
    # The id cannot be reused.
    again = api.post(HOUSES, json={**body, "name": "Other"}, headers=staff)
    assert again.status_code == 422


def test_patch_house(api, staff):
    resp = api.patch(f"{HOUSES}/{HOUSE_A2}", json={"address": "2 Oak Ave"}, headers=staff)
    assert resp.status_code == 200
    assert resp.json()["data"]["address"] == "2 Oak Ave"
    assert resp.json()["data"]["name"] == "Oak Ave"
    dup = api.patch(f"{HOUSES}/{HOUSE_A2}", json={"name": "Maple St"}, headers=staff)
    assert dup.status_code == 422
    null = api.patch(f"{HOUSES}/{HOUSE_A2}", json={"timezone": None}, headers=staff)
    assert null.status_code == 422


def test_owner_cannot_patch_or_delete(api, owner):
    assert (
        api.patch(f"{HOUSES}/{HOUSE_A1}", json={"address": "x"}, headers=owner).status_code == 403
    )
    assert api.delete(f"{HOUSES}/{HOUSE_A1}", headers=owner).status_code == 403


def test_delete_house_with_enabled_feed_is_409(api, staff, seeded):
    from app.models import House

    maple = seeded.get(House, HOUSE_A1)
    seeded.add(make_feed(maple, ROOM_A1_KITCHEN, is_enabled=True, status="active"))
    seeded.flush()
    resp = api.delete(f"{HOUSES}/{HOUSE_A1}", headers=staff)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "house_not_empty"


def test_delete_house_soft_deletes_and_frees_name(api, staff):
    assert api.delete(f"{HOUSES}/{HOUSE_A2}", headers=staff).status_code == 204
    assert api.get(f"{HOUSES}/{HOUSE_A2}", headers=staff).status_code == 404
    assert names(api.get(HOUSES, headers=staff)) == ["Maple St"]
    assert (
        api.post(HOUSES, json={"name": "Oak Ave", "timezone": "UTC"}, headers=staff).status_code
        == 201
    )


def test_cross_tenant_write_is_404(api, staff_b):
    assert (
        api.patch(f"{HOUSES}/{HOUSE_A1}", json={"address": "x"}, headers=staff_b).status_code == 404
    )
    assert api.delete(f"{HOUSES}/{HOUSE_A1}", headers=staff_b).status_code == 404


# --- rooms ----------------------------------------------------------------------------------


def test_list_rooms_sorted(api, staff, owner):
    resp = api.get(f"{HOUSES}/{HOUSE_A1}/rooms", headers=staff)
    assert resp.status_code == 200
    assert [r["name"] for r in resp.json()["data"]] == ["Bathroom", "Kitchen"]
    assert api.get(f"{HOUSES}/{HOUSE_A1}/rooms", headers=owner).status_code == 200
    assert api.get(f"{HOUSES}/{HOUSE_A2}/rooms", headers=owner).status_code == 404


def test_create_rename_delete_room(api, staff):
    resp = api.post(
        f"{HOUSES}/{HOUSE_A2}/rooms", json={"name": "Hall", "room_type": "entry"}, headers=staff
    )
    assert resp.status_code == 201
    room_id = resp.json()["data"]["room_id"]
    renamed = api.patch(f"/api/v1/rooms/{room_id}", json={"name": "Front Hall"}, headers=staff)
    assert renamed.status_code == 200
    assert renamed.json()["data"]["name"] == "Front Hall"
    assert renamed.json()["data"]["room_type"] == "entry"
    assert api.delete(f"/api/v1/rooms/{room_id}", headers=staff).status_code == 204
    assert api.get(f"{HOUSES}/{HOUSE_A2}/rooms", headers=staff).json()["data"] == []


def test_room_validation(api, staff):
    bad_type = api.post(
        f"{HOUSES}/{HOUSE_A1}/rooms", json={"name": "Den", "room_type": "garage"}, headers=staff
    )
    assert bad_type.status_code == 422
    dup = api.post(
        f"{HOUSES}/{HOUSE_A1}/rooms",
        json={"name": "kitchen", "room_type": "kitchen"},
        headers=staff,
    )
    assert dup.status_code == 422
    assert dup.json()["error"]["details"][0]["field"] == "name"
    rename_dup = api.patch(f"/api/v1/rooms/{ROOM_A1_BATH}", json={"name": "Kitchen"}, headers=staff)
    assert rename_dup.status_code == 422


def test_delete_room_in_use_is_409(api, staff, seeded):
    from app.models import House

    maple = seeded.get(House, HOUSE_A1)
    seeded.add(make_feed(maple, ROOM_A1_BATH))
    seeded.flush()
    resp = api.delete(f"/api/v1/rooms/{ROOM_A1_BATH}", headers=staff)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "room_in_use"


def test_delete_room_with_only_archived_feed_detaches_it(api, staff, seeded):
    from datetime import UTC, datetime

    from app.models import CameraFeed, House

    maple = seeded.get(House, HOUSE_A1)
    feed = make_feed(maple, ROOM_A1_BATH, archived_at=datetime.now(UTC))
    seeded.add(feed)
    seeded.flush()
    assert api.delete(f"/api/v1/rooms/{ROOM_A1_BATH}", headers=staff).status_code == 204
    seeded.expire_all()
    assert seeded.get(CameraFeed, feed.feed_id).room_id is None


def test_rooms_of_other_tenant_are_404(api, staff):
    assert api.get(f"{HOUSES}/{HOUSE_B1}/rooms", headers=staff).status_code == 404
    assert (
        api.patch(f"/api/v1/rooms/{ROOM_B1_KITCHEN}", json={"name": "x"}, headers=staff).status_code
        == 404
    )
    assert api.delete(f"/api/v1/rooms/{ROOM_B1_KITCHEN}", headers=staff).status_code == 404
