import { expect, test } from "vitest";
import { cacheMemberOptions } from "./cacheMemberOptions";
import type { ResourceOperation } from "./types";

const member = {
  member_id: "member-a",
  group_name: "shared-cache",
  ip: "10.0.0.8",
  port: 21000,
  state: 3,
};
const listing = (data: unknown): ResourceOperation => ({
  id: "cache-list",
  action: "cache.list",
  state: "succeeded",
  result: { steps: [{ returncode: 0, data }] },
});
const response = (members: unknown) => ({
  groups: { error: { code: 0 }, result: { groups: [] } },
  members: { error: { code: 0 }, result: { members } },
});

test("member options use the live member ID, group, address and offline state", () => {
  expect(cacheMemberOptions(listing(response([member])))).toEqual([
    {
      id: "member-a",
      groupName: "shared-cache",
      address: "10.0.0.8:21000",
      stateLabel: "离线",
      selectable: true,
    },
  ]);
});

test.each([
  [0, true],
  [3, true],
  ["0", true],
  ["3", true],
  ["CacheGroupMemberStateUnknown", true],
  ["CacheGroupMemberStateOffline", true],
  [1, false],
  [2, false],
  ["1", false],
  ["CacheGroupMemberStateOnline", false],
  ["Offline", false],
  [undefined, false],
  [null, false],
  [false, false],
  [true, false],
  [99, false],
])(
  "member state %s is selectable only when explicitly deletable",
  (state, selectable) => {
    const options = cacheMemberOptions(
      listing(response([{ ...member, state }])),
    );
    expect(options[0].selectable).toBe(selectable);
  },
);

test.each([
  { members: { members: [member] } },
  { result: { members: [member] } },
  { members: [member] },
])("accepts supported unwrapped member responses", (data) => {
  expect(cacheMemberOptions(listing(data))[0].id).toBe("member-a");
});

test("reads a JSON stdout response when structured data is absent", () => {
  const operation = listing(undefined);
  operation.result!.steps![0].stdout = JSON.stringify(response([member]));
  expect(cacheMemberOptions(operation)[0].id).toBe("member-a");
});

test("an explicitly empty members array is a valid empty list", () => {
  expect(cacheMemberOptions(listing(response([])))).toEqual([]);
});

test.each([
  undefined,
  null,
  {},
  { groups: { result: { members: [member] } } },
  { members: { result: {} } },
  response(null),
  response("not an array"),
  response([null]),
  response([[member]]),
])("malformed member responses raise a useful Chinese error", (data) => {
  expect(() => cacheMemberOptions(listing(data))).toThrow(
    /缓存成员|缓存组成员/,
  );
});

test.each([undefined, null, "", "   ", 42, {}, []])(
  "invalid member identity %s never falls back to another field",
  (member_id) => {
    expect(() =>
      cacheMemberOptions(
        listing(response([{ ...member, member_id, id: "fallback" }])),
      ),
    ).toThrow(/有效.*ID|ID.*有效/);
  },
);

test("identical duplicate member IDs reject the entire list", () => {
  expect(() =>
    cacheMemberOptions(listing(response([member, { ...member }]))),
  ).toThrow(/重复|冲突/);
});

test.each([
  { group_name: "other-group" },
  { ip: "10.0.0.9" },
  { port: 21001 },
  { state: 1 },
])("conflicting rows sharing an ID reject the entire list", (changes) => {
  expect(() =>
    cacheMemberOptions(listing(response([member, { ...member, ...changes }]))),
  ).toThrow(/冲突|不一致/);
});

test("the member ID preserves separate members sharing a group and address", () => {
  expect(
    cacheMemberOptions(
      listing(response([member, { ...member, member_id: "member-b" }])),
    ).map((option) => option.id),
  ).toEqual(["member-a", "member-b"]);
});

test("failed response envelopes never expose returned rows as selectable members", () => {
  expect(() =>
    cacheMemberOptions(
      listing({
        members: { error: { code: 5 }, result: { members: [member] } },
      }),
    ),
  ).toThrow(/失败|错误/);
  expect(() =>
    cacheMemberOptions(
      listing({
        members: { result: { error: { errcode: 5 }, members: [member] } },
      }),
    ),
  ).toThrow(/失败|错误/);
});

test("IPv6 member addresses remain unambiguous", () => {
  expect(
    cacheMemberOptions(listing(response([{ ...member, ip: "::1" }])))[0]
      .address,
  ).toBe("[::1]:21000");
});

test.each([0, "0", "OK", "kOk", null, undefined, false])(
  "backend success code %s accepts returned members",
  (code) => {
    expect(
      cacheMemberOptions(
        listing({
          members: {
            error: { code },
            result: { error: { errcode: code }, members: [member] },
          },
        }),
      )[0].id,
    ).toBe("member-a");
  },
);

test("boolean true error codes remain failures", () => {
  expect(() =>
    cacheMemberOptions(
      listing({
        members: { error: { code: true }, result: { members: [member] } },
      }),
    ),
  ).toThrow(/失败|错误/);
});
