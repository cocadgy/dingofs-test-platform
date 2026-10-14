import { Scenario, Spec } from "./types";
// total_size is derived from file_size × file_count, not an independent axis.
const dimensions: (keyof Spec)[] = [
  "rw",
  "direct",
  "concurrency",
  "iodepth",
  "block_size",
  "file_size",
  "file_count",
  "rounds",
  "read_percent",
];
export function chartGroups(rows: Scenario[], parameter: keyof Spec) {
  const groups = new Map<
    string,
    { key: string; fixed: Partial<Spec>; scenes: Scenario[] }
  >();
  for (const scene of rows) {
    const fixed = Object.fromEntries(
      (scene.tool === "mdtest" ? ["concurrency","file_count","rounds","layout","mdtest_options"] as (keyof Spec)[] : dimensions)
        .filter(
          (key) =>
            key !== parameter &&
            !(parameter === "rw" && key === "read_percent"),
        )
        .map((key) => [
          key,
          key === "read_percent" &&
          !["rw", "randrw"].includes(scene.parameters.rw)
            ? null
            : (scene.parameters[key] ?? null),
        ]),
    ) as Partial<Spec>;
    const key = JSON.stringify(fixed);
    if (!groups.has(key)) groups.set(key, { key, fixed, scenes: [] });
    groups.get(key)!.scenes.push(scene);
  }
  return [...groups.values()];
}
