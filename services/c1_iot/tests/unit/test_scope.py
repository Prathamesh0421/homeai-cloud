"""Scope rules (C1 plan §4.3): who sees which tenant and houses."""

from __future__ import annotations

from app.repositories.scope import Scope
from homeai_common.auth import Principal

from tests.factories import HOUSE_A1, HOUSE_A2, TENANT_A, TENANT_B


def user(role: str, tenant_id: str | None = TENANT_A, house_ids: tuple[str, ...] = ()) -> Principal:
    return Principal(kind="user", sub="u", role=role, tenant_id=tenant_id, house_ids=house_ids)


def service() -> Principal:
    return Principal(kind="service", sub="c4-dashboard", role=None, tenant_id=None)


def test_iot_staff_is_limited_to_own_tenant_and_ignores_tenant_filter():
    scope = Scope.for_principal(user("iot_staff"), tenant_id=TENANT_B)
    assert scope == Scope(tenant_id=TENANT_A)


def test_cloud_staff_sees_everything_or_the_tenant_asked_for():
    assert Scope.for_principal(user("cloud_staff", tenant_id=None)) == Scope()
    assert Scope.for_principal(user("cloud_staff"), TENANT_B) == Scope(tenant_id=TENANT_B)


def test_owner_is_limited_to_own_houses():
    scope = Scope.for_principal(user("house_owner", house_ids=(HOUSE_A1,)))
    assert scope == Scope(tenant_id=TENANT_A, house_ids=(HOUSE_A1,))
    assert scope.allows(TENANT_A, HOUSE_A1)
    assert not scope.allows(TENANT_A, HOUSE_A2)
    assert not scope.allows(TENANT_B, HOUSE_A1)


def test_owner_without_houses_sees_nothing():
    scope = Scope.for_principal(user("house_owner"))
    assert scope.house_ids == ()
    assert not scope.allows(TENANT_A, HOUSE_A1)
    assert scope.mongo_filter() == {"tenant_id": TENANT_A, "house_id": {"$in": []}}


def test_service_token_sees_any_tenant_with_optional_filter():
    assert Scope.for_principal(service()) == Scope()
    assert Scope.for_principal(service(), TENANT_A) == Scope(tenant_id=TENANT_A)


def test_mongo_filter_matches_sql_scope():
    assert Scope().mongo_filter() == {}
    assert Scope(tenant_id=TENANT_A).mongo_filter() == {"tenant_id": TENANT_A}
    scope = Scope(tenant_id=TENANT_A, house_ids=(HOUSE_A1, HOUSE_A2))
    assert scope.mongo_filter() == {
        "tenant_id": TENANT_A,
        "house_id": {"$in": [HOUSE_A1, HOUSE_A2]},
    }
