import { expect, test } from "vitest";
import { blankCacheDraft, cacheMembers, newCacheRow } from "./guidedCacheModel";
const machine = { id: "m", name: "m", address: "1.2.3.4", ssh_user: "u", can_manage: true };
test("per-machine weights override template and expand to every node", () => {
  const draft = { ...blankCacheDraft(), options: { group_weight: "250" }, rows: [
    { ...newCacheRow(machine), directory: "/cache", count: 2, weight: 50 },
    { ...newCacheRow({ ...machine, id: "m2" }), directory: "/cache", weight: 200 },
    { ...newCacheRow({ ...machine, id: "m3" }), directory: "/cache" },
  ] };
  expect(cacheMembers(draft).map(m => m.group_weight)).toEqual([50, 50, 200, 250]);
  expect(cacheMembers({ ...draft, options: {}, rows: [draft.rows[2]] })[0].group_weight).toBe(100);
  expect(cacheMembers({ ...draft, rows: [{ ...draft.rows[0], count: 1, weight: 0 }] })[0].group_weight).toBe(0);
});
