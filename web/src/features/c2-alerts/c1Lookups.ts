/** House and room names from C1 for the Alert Rules pages (cloud staff see every tenant's houses).
 *
 * C2 stores only ids; the pages ask C1 for names with the user's own token. When C1 cannot be
 * reached the pages fall back to typed ids, so rules can still be managed.
 */

import { useQueries, useQuery } from "@tanstack/react-query";
import { c1Keys, listHouses, listRooms, type House, type Room } from "../../api/c1";

export const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const HOUSES = { pageSize: 100 } as const; // C1's page_size limit
const STALE_MS = 300_000;

export function useHouses() {
  return useQuery({ queryKey: c1Keys.houses(HOUSES), queryFn: () => listHouses(HOUSES), staleTime: STALE_MS });
}

/** A house's rooms; idle until ``houseId`` is a whole id. */
export function useRooms(houseId: string | null | undefined) {
  const id = houseId && UUID.test(houseId) ? houseId : "";
  return useQuery({
    queryKey: c1Keys.rooms(id),
    queryFn: () => listRooms(id),
    enabled: id !== "",
    staleTime: STALE_MS,
  });
}

/** Room id -> room, for the rooms of these houses (rooms that fail to load are left out). */
export function useRoomsOf(houseIds: string[]): Map<string, Room> {
  const results = useQueries({
    queries: houseIds.map((id) => ({ queryKey: c1Keys.rooms(id), queryFn: () => listRooms(id), staleTime: STALE_MS })),
  });
  return new Map(results.flatMap((r) => r.data ?? []).map((r) => [r.room_id, r]));
}

export function houseMap(houses: House[] | undefined): Map<string, House> {
  return new Map((houses ?? []).map((h) => [h.house_id, h]));
}
