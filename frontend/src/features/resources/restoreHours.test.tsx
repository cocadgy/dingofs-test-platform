import { expect, test } from "vitest";
import { restoreHourBuckets } from "./restoreHours";
test("restore uses UTC hour buckets that cover the entire requested interval", () => {
  expect(restoreHourBuckets(1, new Date("2026-10-13T02:15:00Z"))).toBe("2026-10-13-01,2026-10-13-02");
  expect(restoreHourBuckets(2, new Date("2026-10-13T00:15:00Z"))).toBe("2026-10-12-22,2026-10-12-23,2026-10-13-00");
});
