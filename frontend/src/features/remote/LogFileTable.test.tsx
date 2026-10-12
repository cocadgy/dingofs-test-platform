import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { LogFileTable } from "./LogFileTable";
import type { RemoteFile } from "./types";

afterEach(cleanup);
const files: RemoteFile[] = [
  { file_id: "ten", name: "file10.txt", size: 1024, mtime: 100 },
  {
    file_id: "two",
    name: "file2.log.1",
    size: 20,
    mtime: "1970-01-01T00:05:00Z",
  },
  { file_id: "one", name: "file1.json", size: 3, mtime: 200 },
];
function names() {
  return screen
    .getAllByRole("row")
    .slice(1)
    .map((row) => within(row).getAllByRole("cell")[0].textContent);
}
function row(name: string) {
  return screen.getByRole("cell", { name }).closest("tr")!;
}
function sort(label: string) {
  fireEvent.click(screen.getByRole("button", { name: label }));
}

test("renders detail columns with newest numeric or date-string timestamps first without mutating files", () => {
  const frozen = files.map((file) => Object.freeze({ ...file }));
  Object.freeze(frozen);
  render(<LogFileTable files={frozen} onOpen={() => {}} />);
  expect(
    screen
      .getAllByRole("columnheader")
      .map((header) => header.textContent?.replace(/[↑↓]/g, "").trim()),
  ).toEqual(["名称", "修改时间", "类型", "大小"]);
  expect(names()).toEqual(["file2.log.1", "file1.json", "file10.txt"]);
  expect(
    screen.getByRole("columnheader", { name: "修改时间" }),
  ).toHaveAttribute("aria-sort", "descending");
  expect(within(row("file10.txt")).getByText("1.0 KiB")).toBeInTheDocument();
  sort("名称");
  expect(frozen.map((file) => file.file_id)).toEqual(["ten", "two", "one"]);
});

test.each([
  ["名称", ["file1.json", "file2.log.1", "file10.txt"]],
  ["大小", ["file1.json", "file2.log.1", "file10.txt"]],
  ["修改时间", ["file10.txt", "file1.json", "file2.log.1"]],
  ["类型", ["file2.log.1", "file10.txt", "file1.json"]],
] as const)(
  "%s header toggles ascending and descending order",
  (label, ascending) => {
    render(<LogFileTable files={files} onOpen={() => {}} />);
    sort(label);
    expect(names()).toEqual(ascending);
    expect(screen.getByRole("columnheader", { name: label })).toHaveAttribute(
      "aria-sort",
      "ascending",
    );
    sort(label);
    expect(names()).toEqual([...ascending].reverse());
    expect(screen.getByRole("columnheader", { name: label })).toHaveAttribute(
      "aria-sort",
      "descending",
    );
  },
);

test.each(["修改时间", "大小"])(
  "%s keeps invalid and missing metadata last in both directions",
  (label) => {
    const invalid = [
      { file_id: "bad", name: "invalid.log", size: NaN, mtime: "not a date" },
      {
        file_id: "missing",
        name: "missing.log",
        size: undefined,
        mtime: undefined,
      },
    ] as unknown as RemoteFile[];
    render(<LogFileTable files={[...invalid, ...files]} onOpen={() => {}} />);
    sort(label);
    expect(names().slice(-2)).toEqual(["invalid.log", "missing.log"]);
    sort(label);
    expect(names().slice(-2)).toEqual(["invalid.log", "missing.log"]);
    expect(within(row("invalid.log")).getAllByText("—")).toHaveLength(2);
  },
);

test("infers readable file types and renders filenames as plain text", () => {
  const examples = [
    ["server.LOG", "日志文件"],
    ["server.log.12", "日志文件"],
    ["README", "文件"],
    ["settings.yaml", "YAML 文件"],
    ["server.log.gz", "GZ 压缩文件"],
    ["<img src=x onerror=alert(1)>.txt", "文本文档"],
  ];
  const { container } = render(
    <LogFileTable
      files={examples.map(([name], index) => ({
        file_id: String(index),
        name,
        size: 0,
        mtime: 0,
      }))}
      onOpen={() => {}}
    />,
  );
  for (const [name, type] of examples)
    expect(within(row(name)).getByText(type)).toBeInTheDocument();
  expect(container.querySelector("img")).toBeNull();
});

test("single click selects without opening; double click opens once and selection survives sorting", () => {
  const onOpen = vi.fn();
  render(<LogFileTable files={files} onOpen={onOpen} />);
  const selected = row("file2.log.1");
  fireEvent.click(selected);
  expect(selected).toHaveAttribute("aria-selected", "true");
  expect(onOpen).not.toHaveBeenCalled();
  sort("名称");
  expect(row("file2.log.1")).toHaveAttribute("aria-selected", "true");
  fireEvent.click(selected);
  fireEvent.click(selected);
  fireEvent.doubleClick(selected);
  expect(onOpen).toHaveBeenCalledTimes(1);
  expect(onOpen).toHaveBeenCalledWith(files[1]);
});

test("focus selects a keyboard row and Enter opens it without repeating on a held key", () => {
  const onOpen = vi.fn();
  render(<LogFileTable files={files} onOpen={onOpen} />);
  const focused = row("file10.txt");
  expect(focused).toHaveAttribute("tabindex", "0");
  fireEvent.focus(focused);
  expect(focused).toHaveAttribute("aria-selected", "true");
  fireEvent.keyDown(focused, { key: "Enter" });
  fireEvent.keyDown(focused, { key: "Enter", repeat: true });
  expect(onOpen).toHaveBeenCalledTimes(1);
  expect(onOpen).toHaveBeenCalledWith(files[0]);
});

test("disabled rows cannot select or open files", () => {
  const onOpen = vi.fn();
  render(<LogFileTable files={files} disabled onOpen={onOpen} />);
  const disabled = row("file10.txt");
  expect(disabled).toHaveAttribute("tabindex", "-1");
  fireEvent.click(disabled);
  fireEvent.focus(disabled);
  fireEvent.doubleClick(disabled);
  fireEvent.keyDown(disabled, { key: "Enter" });
  expect(disabled).toHaveAttribute("aria-selected", "false");
  expect(onOpen).not.toHaveBeenCalled();
});

test("recognizes glog severity aliases and timestamped logs while preserving compressed and other extensions", () => {
  const examples = [
    ["mds.INFO", "日志文件"],
    ["mds.WARNING", "日志文件"],
    ["mds.ERROR", "日志文件"],
    ["mds.FATAL", "日志文件"],
    ["mds.INFO.20261009-111500.123", "日志文件"],
    ["mds.WARNING.20261009-111501", "日志文件"],
    ["mds.ERROR.20261009-111502.456", "日志文件"],
    ["mds.FATAL.20261009-111503.789", "日志文件"],
    ["mds.INFO.20261009-111500.123.gz", "GZ 压缩文件"],
    ["mds.ERROR.zip", "ZIP 压缩文件"],
    ["mds.INFO.txt", "文本文档"],
    ["mds.INFO.20261009-111500.extra", "EXTRA 文件"],
  ];
  render(
    <LogFileTable
      files={examples.map(([name], index) => ({
        file_id: String(index),
        name,
        size: 0,
        mtime: 0,
      }))}
      onOpen={() => {}}
    />,
  );
  for (const [name, type] of examples)
    expect(within(row(name)).getByText(type)).toBeInTheDocument();
});
