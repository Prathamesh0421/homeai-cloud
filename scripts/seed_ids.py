"""Fixed IDs of the demo/seed data (docs/03_REPO_AND_INFRA.md §7), shared by every component.

`scripts/seed.py` (P0-10) creates the rows with these IDs; demo scripts, integration tests and
the docs refer to them. Pattern: the first block says what it is, the last block numbers it.

| Kind     | Pattern                                  | Example                                  |
|----------|------------------------------------------|------------------------------------------|
| tenant   | 11111111-0000-0000-0000-0000000000NN     | Acme Care = ...0001                      |
| house    | 22222222-0000-0000-0000-0000000000HH     | Maple St = ...00a1 (tenant a, house 1)   |
| room     | 33333333-0000-0000-0000-00000000HHRR     | Maple Bathroom = ...a104                 |
| user     | 44444444-0000-0000-0000-0000000000NN     | ops@homeai.test = ...0001                |
| contact  | 55555555-0000-0000-0000-00000000HHNN     | Maple contact 1 = ...a101                |

Change an ID only together with every component's seed and tests.
"""

from __future__ import annotations

TENANTS = {
    "acme": "11111111-0000-0000-0000-000000000001",  # Acme Care
    "sunrise": "11111111-0000-0000-0000-000000000002",  # Sunrise Living (isolation tests)
}

# alias -> (house_id, tenant alias, name, timezone)
HOUSES = {
    "maple": ("22222222-0000-0000-0000-0000000000a1", "acme", "Maple St", "America/Los_Angeles"),
    "oak": ("22222222-0000-0000-0000-0000000000a2", "acme", "Oak Ave", "America/Los_Angeles"),
    "pine": ("22222222-0000-0000-0000-0000000000b1", "sunrise", "Pine Rd", "America/New_York"),
}

ROOM_NAMES = ("Kitchen", "Bedroom 1", "Living", "Bathroom", "Entryway")  # same in every house


def room_id(house: str, room: str) -> str:
    """``room_id("maple", "Bathroom")`` -> ``33333333-...-0000a104``."""
    house_code = HOUSES[house][0][-2:]
    return f"33333333-0000-0000-0000-00000000{house_code}{ROOM_NAMES.index(room) + 1:02d}"


ROOMS = {(house, name): room_id(house, name) for house in HOUSES for name in ROOM_NAMES}

# email -> (user_id, role, tenant alias or None for platform staff, house aliases)
USERS = {
    "ops@homeai.test": ("44444444-0000-0000-0000-000000000001", "cloud_staff", None, ()),
    "owner.maple@acme.test": (
        "44444444-0000-0000-0000-000000000002",
        "house_owner",
        "acme",
        ("maple",),
    ),
    "owner.oak@acme.test": (
        "44444444-0000-0000-0000-000000000003",
        "house_owner",
        "acme",
        ("oak",),
    ),
    "iot@acme.test": ("44444444-0000-0000-0000-000000000004", "iot_staff", "acme", ()),
    "owner.sun@sunrise.test": (
        "44444444-0000-0000-0000-000000000005",
        "house_owner",
        "sunrise",
        ("pine",),
    ),
}

# Maple's emergency contacts, in priority order (real team emails go in for the demo).
MAPLE_CONTACTS = (
    "55555555-0000-0000-0000-00000000a101",
    "55555555-0000-0000-0000-00000000a102",
    "55555555-0000-0000-0000-00000000a103",
)

SERVICE_CLIENTS = ("c2-alerts", "c3-worker", "c3-data", "c4-dashboard", "device-uploader")


def house_id(alias_or_id: str) -> str:
    """A house alias (``maple``) or a UUID, returned as the UUID."""
    entry = HOUSES.get(alias_or_id.lower())
    return entry[0] if entry else alias_or_id


def tenant_of(house: str) -> str:
    """Tenant UUID of a seeded house (alias or UUID)."""
    hid = house_id(house)
    for seeded, tenant, _, _ in HOUSES.values():
        if seeded == hid:
            return TENANTS[tenant]
    raise KeyError(f"not a seeded house: {house}")
