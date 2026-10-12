import { expect, test } from "vitest";
import { shellMatches } from "./shellPattern";

test.each([
  ["vdbench*", "vdbench", true],
  ["vdbench*", "vdbench-001", true],
  ["vdbench*", "prefix-vdbench", false],
  ["vdbench.*", "vdbench-001", false],
  ["vdbench.*", "vdbench.001", true],
  ["test?", "test1", true],
  ["test?", "test12", false],
  ["test[0-9]", "test3", true],
  ["test[!0-9]", "testa", true],
  ["test[!0-9]", "test3", false],
  ["test[ab]", "testb", true],
  ["a+b", "aaab", false],
  ["a+b", "a+b", true],
  ["[", "[", true],
  ["*", ".hidden", false],
  [".*", ".hidden", true],
  ["", "name", false],
  ["a\\*", "a*", true],
])("%s matches %s: %s", (pattern, name, expected) => {
  expect(shellMatches(pattern, name)).toBe(expected);
});
