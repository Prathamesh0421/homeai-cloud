"""C3-10 (unit): role -> RecordScope mapping and the Mongo filter it produces."""

from __future__ import annotations

import pytest
from app.services.record_scope import record_scope
from homeai_common.auth import Principal
from homeai_common.errors import ApiError


def _user(role, tenant_id="t1", house_ids=()):
    return Principal(
        kind="user", sub="u1", role=role, tenant_id=tenant_id, house_ids=tuple(house_ids)
    )


def _service(scopes=("records:read",)):
    return Principal(kind="service", sub="c4-dashboard", role=None, tenant_id=None, scopes=scopes)


def test_house_owner_scoped_to_own_tenant_and_houses():
    s = record_scope(_user("house_owner", "t1", ["h1", "h2"]), tenant_id="tOTHER")
    assert s.tenant_id == "t1"  # query tenant_id ignored
    assert s.house_ids == ("h1", "h2")


def test_iot_staff_scoped_to_own_tenant_all_houses():
    s = record_scope(_user("iot_staff", "t1"), tenant_id=None)
    assert s.tenant_id == "t1"
    assert s.house_ids is None


def test_cloud_staff_all_tenants_optionally_narrowed():
    assert record_scope(_user("cloud_staff"), tenant_id=None).tenant_id is None
    assert record_scope(_user("cloud_staff"), tenant_id="tX").tenant_id == "tX"


def test_service_behaves_like_cloud_staff():
    assert record_scope(_service(), tenant_id="tX").tenant_id == "tX"


def test_mongo_filter_empty_houses_matches_nothing():
    s = record_scope(_user("house_owner", "t1", []))  # owner with no houses
    flt = s.mongo_filter()
    assert flt["tenant_id"] == "t1"
    assert flt["house_id"] == {"$in": []}


def test_unknown_principal_rejected():
    # A user with no recognised role.
    with pytest.raises(ApiError) as e:
        record_scope(_user("stranger"))
    assert e.value.status_code == 403
