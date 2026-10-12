export async function copyText(value: string): Promise<void> {
  try {
    if (typeof navigator.clipboard?.writeText === "function") {
      await navigator.clipboard.writeText(value);
      return;
    }
  } catch {
    // HTTP deployments and browser permissions can prevent Clipboard API use.
  }

  const focused = document.activeElement;
  const input =
    focused instanceof HTMLInputElement ||
    focused instanceof HTMLTextAreaElement
      ? focused
      : undefined;
  const inputSelection = input
    ? {
        start: input.selectionStart,
        end: input.selectionEnd,
        direction: input.selectionDirection,
      }
    : undefined;
  const selection = window.getSelection();
  const ranges = selection
    ? Array.from({ length: selection.rangeCount }, (_, index) =>
        selection.getRangeAt(index).cloneRange(),
      )
    : [];
  const buffer = document.createElement("textarea");
  buffer.className = "clipboard-copy-buffer";
  buffer.value = value;
  buffer.readOnly = true;
  buffer.tabIndex = -1;
  buffer.setAttribute("aria-hidden", "true");
  try {
    document.body.append(buffer);
    buffer.focus({ preventScroll: true });
    buffer.select();
    buffer.setSelectionRange(0, value.length);
    if (document.execCommand("copy") !== true) throw new Error("copy rejected");
  } catch {
    throw new Error("复制失败，请手动选择并复制内容。");
  } finally {
    buffer.remove();
    try {
      if (focused instanceof HTMLElement)
        focused.focus({ preventScroll: true });
    } catch {
      // The original control may have been removed while copying.
    }
    try {
      if (selection) {
        selection.removeAllRanges();
        for (const range of ranges) selection.addRange(range);
      }
      if (input && inputSelection?.start != null && inputSelection.end != null)
        input.setSelectionRange(
          inputSelection.start,
          inputSelection.end,
          inputSelection.direction ?? undefined,
        );
    } catch {
      // Restore selections when the original DOM and control still allow it.
    }
  }
}
