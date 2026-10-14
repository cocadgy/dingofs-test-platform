import { expect, test } from "vitest";
import { chartGroups } from "./chartGroups";
import { Scenario } from "./types";
const rows: Scenario[] = [];
for (const concurrency of [1, 2, 4])
  for (const direct of [false, true])
    for (const block_size of ["4096", "65536"])
      rows.push({
        id: String(rows.length),
        tool: "fio",
        parameters: {
          tool: "fio",
          concurrency,
          direct,
          block_size,
          rw: "read",
          iodepth: 1,
          file_size: "1048576",
          file_count: 1,
          total_size: "1048576",
          rounds: 2,
          read_percent: 50,
        },
      });
test("3 concurrency values × 2 direct modes × 2 block sizes yields 4 groups each containing 3 bars", () => {
  const groups = chartGroups(rows, "concurrency");
  expect(groups).toHaveLength(4);
  for (const group of groups)
    expect(group.scenes.map((s) => s.parameters.concurrency)).toEqual([
      1, 2, 4,
    ]);
  expect(chartGroups(rows, "direct")).toHaveLength(6);
  for (const group of chartGroups(rows, "direct"))
    expect(group.scenes.map((s) => s.parameters.direct)).toEqual([false, true]);
});
test("derived total size does not split file-size comparisons; file count still separates groups", () => {
  const a = rows[0];
  const b = {
    ...a,
    id: "larger",
    parameters: {
      ...a.parameters,
      file_size: "2097152",
      total_size: "2097152",
    },
  };
  expect(chartGroups([a, b], "file_size")).toHaveLength(1);
  expect(
    chartGroups(
      [a, { ...b, parameters: { ...b.parameters, file_count: 2 } }],
      "file_size",
    ),
  ).toHaveLength(2);
});

test("read/write comparison keeps pure and mixed modes together per direct setting", () => {
  const cases: Scenario[] = [];
  for (const direct of [true, false])
    for (const [rw, read_percent] of [
      ["write", null],
      ["rw", 50],
      ["rw", 70],
    ] as const)
      cases.push({
        ...rows[0],
        id: String(cases.length),
        parameters: {
          ...rows[0].parameters,
          direct,
          rw,
          read_percent: read_percent as unknown as number,
        },
      });
  const groups = chartGroups(cases, "rw");
  expect(groups).toHaveLength(2);
  for (const group of groups) {
    expect(group.scenes).toHaveLength(3);
    expect(group.fixed).not.toHaveProperty("read_percent");
  }
  expect(chartGroups(cases, "direct")).toHaveLength(3);
});
