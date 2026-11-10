/**
 * House id → display name helpers for C4 pages.
 *
 * REPLACE_WHEN_C1: When C1 ships `GET /api/v1/houses`, delete SEED_HOUSES and
 * resolve names via that API (scoped by tenant). Until then we use the fixed
 * IDs from scripts/seed_ids.py so Settings / Tenants / Dashboard work on EC2.
 */

export interface HouseOption {
  house_id: string;
  name: string;
  tenant_alias: string;
}

/** Seed houses from scripts/seed_ids.py — temporary until C1 houses API exists. */
export const SEED_HOUSES: HouseOption[] = [
  {
    house_id: "22222222-0000-0000-0000-0000000000a1",
    name: "Maple St",
    tenant_alias: "acme",
  },
  {
    house_id: "22222222-0000-0000-0000-0000000000a2",
    name: "Oak Ave",
    tenant_alias: "acme",
  },
];

export function houseLabel(houseId: string): string {
  const hit = SEED_HOUSES.find((h) => h.house_id === houseId);
  if (hit) return hit.name;
  return houseId.length > 8 ? `…${houseId.slice(-8)}` : houseId;
}

/** Options for an owner (their house_ids) or cloud_staff (all seed houses). */
export function houseOptionsFor(
  role: string,
  houseIds: string[],
): HouseOption[] {
  if (role === "cloud_staff") return [...SEED_HOUSES];
  return houseIds.map((id) => {
    const seeded = SEED_HOUSES.find((h) => h.house_id === id);
    return seeded ?? { house_id: id, name: houseLabel(id), tenant_alias: "" };
  });
}
