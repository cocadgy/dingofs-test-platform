import { expect, test } from "vitest";
import catalog from "./fixtures/cache-create-catalog.json";
import { defaults, newMember, type ResourceAction } from "./types";
const action = catalog as ResourceAction;
test("legacy member creation inherits group options with the real server catalogue", () => {
  const field = action.fields.find(f => f.key === "members")!;
  expect(field.fields?.some(f => f.key === "cache_options")).toBe(true);
  for (const member of [newMember(field), ...(defaults(action).members as Record<string, unknown>[])]) {
    expect(member).not.toHaveProperty("cache_options");
    expect(member).not.toHaveProperty("cache_profile_id");
    expect(member).not.toHaveProperty("cache_profile_revision");
    expect(member.port_mode).toBe("auto");
    expect(member.cache_size_mb).toBe(1024);
  }
});
