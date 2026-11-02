import { expect, test } from "vitest";
import { formatFilesystemName } from "./filesystemName";

const time = new Date(2026, 10, 2, 18, 15, 30, 123);

test.each([
  ["none", "training"],
  ["date", "training-20261102"],
  ["seconds", "training-20261102-181530"],
  ["milliseconds", "training-20261102-181530-123"],
] as const)("formats the selected suffix %s", (format, expected) => {
  expect(formatFilesystemName(" training ", format, time)).toBe(expected);
});
