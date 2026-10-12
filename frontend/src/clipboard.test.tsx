import { afterEach, expect, test, vi } from "vitest";
import { copyText } from "./clipboard";

const clipboardDescriptor = Object.getOwnPropertyDescriptor(
  navigator,
  "clipboard",
);
const commandDescriptor = Object.getOwnPropertyDescriptor(
  document,
  "execCommand",
);
afterEach(() => {
  document.body.replaceChildren();
  window.getSelection()?.removeAllRanges();
  if (clipboardDescriptor)
    Object.defineProperty(navigator, "clipboard", clipboardDescriptor);
  else delete (navigator as { clipboard?: Clipboard }).clipboard;
  if (commandDescriptor)
    Object.defineProperty(document, "execCommand", commandDescriptor);
  else
    delete (document as { execCommand?: Document["execCommand"] }).execCommand;
  vi.restoreAllMocks();
});

function clipboard(value: unknown) {
  Object.defineProperty(navigator, "clipboard", { configurable: true, value });
}
function command(implementation: (name: string) => boolean) {
  const execute = vi.fn(implementation);
  Object.defineProperty(document, "execCommand", {
    configurable: true,
    value: execute,
  });
  return execute;
}
function focusedInput() {
  const input = document.createElement("input");
  input.value = "draft selection";
  document.body.append(input);
  input.focus();
  input.setSelectionRange(2, 7, "backward");
  return input;
}
function expectRestored(input: HTMLInputElement) {
  expect(document.activeElement).toBe(input);
  expect(input.selectionStart).toBe(2);
  expect(input.selectionEnd).toBe(7);
  expect(input.selectionDirection).toBe("backward");
  expect(document.querySelector(".clipboard-copy-buffer")).toBeNull();
}

test("uses the Clipboard API without changing focus or adding a buffer", async () => {
  const input = focusedInput();
  const writeText = vi.fn().mockResolvedValue(undefined);
  clipboard({ writeText });
  const execute = command(() => true);
  await copyText("/data/测试 path\nsecond line");
  expect(writeText).toHaveBeenCalledWith("/data/测试 path\nsecond line");
  expect(execute).not.toHaveBeenCalled();
  expectRestored(input);
});

test.each(["missing", "rejected"])(
  "copies exactly the requested text using a selected buffer when the API is %s",
  async (mode) => {
    const input = focusedInput();
    clipboard(
      mode === "missing"
        ? undefined
        : { writeText: vi.fn().mockRejectedValue(new Error("denied")) },
    );
    const text = "/var/lib/中文 path\nline two\tend";
    const execute = command((name) => {
      expect(name).toBe("copy");
      const buffer = document.querySelector<HTMLTextAreaElement>(
        "textarea.clipboard-copy-buffer",
      )!;
      expect(buffer).not.toBeNull();
      expect(buffer.readOnly).toBe(true);
      expect(buffer.tabIndex).toBe(-1);
      expect(buffer.getAttribute("aria-hidden")).toBe("true");
      expect(document.activeElement).toBe(buffer);
      expect(buffer.value).toBe(text);
      expect(
        buffer.value.slice(buffer.selectionStart, buffer.selectionEnd),
      ).toBe(text);
      return true;
    });
    await copyText(text);
    expect(execute).toHaveBeenCalledTimes(1);
    expectRestored(input);
  },
);

test.each(["false", "throws"])(
  "reports fallback failure and restores focus without leaked buffers when copying %s",
  async (mode) => {
    const input = focusedInput();
    clipboard(undefined);
    const execute = command(() => {
      if (mode === "throws") throw new Error("internal clipboard failure");
      return false;
    });
    await expect(copyText("/copy/path")).rejects.toThrow("复制失败");
    expect(execute).toHaveBeenCalledTimes(1);
    expectRestored(input);
  },
);

test("restores an existing document text selection after the fallback", async () => {
  const paragraph = document.createElement("p");
  paragraph.textContent = "keep this selection";
  document.body.append(paragraph);
  const range = document.createRange();
  range.setStart(paragraph.firstChild!, 5);
  range.setEnd(paragraph.firstChild!, 9);
  window.getSelection()!.addRange(range);
  clipboard(undefined);
  const execute = command(() => {
    window.getSelection()!.removeAllRanges();
    return true;
  });
  await copyText("/copy/path");
  expect(execute).toHaveBeenCalledWith("copy");
  expect(window.getSelection()!.toString()).toBe("this");
  expect(document.querySelector(".clipboard-copy-buffer")).toBeNull();
});
