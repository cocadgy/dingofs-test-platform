import { useEffect, useRef, useState } from "react";
import type { Terminal } from "@xterm/xterm";
import "@xterm/xterm/css/xterm.css";
import { terminalDocument, bindTerminalRowDocument } from "./terminalDocument";
import { copyText } from "../../clipboard";
export type TerminalWriter = (text: string, done: () => void) => void;
export function TerminalSurface({
  onReady,
  onData,
  onResize,
  onError,
}: {
  onReady: (write: TerminalWriter | undefined) => void;
  onData: (data: string) => void;
  onResize: (cols: number, rows: number) => void;
  onError: (message: string) => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const terminal = useRef<Terminal | undefined>(undefined);
  const handlers = useRef({ onReady, onData, onResize, onError });
  handlers.current = { onReady, onData, onResize, onError };
  const [message, setMessage] = useState("");
  const [pasteOpen, setPasteOpen] = useState(false);
  const [pasteText, setPasteText] = useState("");
  const pasteInput = useRef<HTMLTextAreaElement>(null);
  function closePaste() {
    setPasteText("");
    setPasteOpen(false);
    terminal.current?.focus();
  }
  useEffect(() => {
    let live = true;
    let dispose = () => {};
    Promise.all([import("@xterm/xterm"), import("@xterm/addon-fit")])
      .then(([{ Terminal }, { FitAddon }]) => {
        if (!live || !container.current) return;
        const styles = terminalDocument(container.current.ownerDocument);
        const term = new Terminal({
          documentOverride: styles.document,
          cols: 100,
          rows: 30,
          cursorBlink: true,
          scrollback: 5000,
          fontSize: 14,
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
          theme: { background: "#101e2b", foreground: "#dae5ed" },
          linkHandler: { activate: () => {} },
          allowProposedApi: true,
        });
        terminal.current = term;
        dispose = () => {
          terminal.current = undefined;
          term.dispose();
          styles.dispose();
        };
        const fit = new FitAddon();
        term.loadAddon(fit);
        // Consume OSC 52 before xterm's default clipboard handler.
        const clipboard = term.parser.registerOscHandler(52, () => true);
        term.open(container.current);
        bindTerminalRowDocument(term, styles.document);
        fit.fit();
        term.focus();
        const input = term.onData((data) => {
          const characters = Array.from(data);
          for (let start = 0; start < characters.length; start += 2048)
            handlers.current.onData(
              characters.slice(start, start + 2048).join(""),
            );
        });
        const resize = term.onResize((size) =>
          handlers.current.onResize(size.cols, size.rows),
        );
        const observer = new ResizeObserver(() => fit.fit());
        observer.observe(container.current);
        handlers.current.onResize(term.cols, term.rows);
        handlers.current.onReady((text, done) => term.write(text, done));
        dispose = () => {
          handlers.current.onReady(undefined);
          observer.disconnect();
          input.dispose();
          resize.dispose();
          clipboard.dispose();
          terminal.current = undefined;
          term.dispose();
          styles.dispose();
        };
      })
      .catch((e) => {
        dispose();
        if (live) handlers.current.onError(`终端加载失败：${e.message}`);
      });
    return () => {
      live = false;
      dispose();
    };
  }, []);
  return (
    <>
      <div className="actions terminal-clipboard">
        <button
          onClick={async () => {
            try {
              const selection = terminal.current?.getSelection();
              if (selection) {
                await copyText(selection);
                setMessage("已复制选中文本");
              } else setMessage("请先选中终端文字");
            } catch {
              setMessage("无法访问剪贴板，请使用浏览器复制快捷键");
            }
          }}
        >
          复制选中内容
        </button>
        <button
          onClick={async () => {
            if (pasteOpen) {
              pasteInput.current?.focus();
              return;
            }
            try {
              const text = await navigator.clipboard.readText();
              terminal.current?.paste(text);
              terminal.current?.focus();
              setMessage("已粘贴到终端");
            } catch {
              setPasteText("");
              setPasteOpen(true);
              setMessage("请在下方粘贴内容，确认后发送。");
            }
          }}
        >
          粘贴
        </button>
        <small role="status">
          {message || "支持 Ctrl+C；复制和粘贴也可使用浏览器快捷键。"}
        </small>
      </div>
      {pasteOpen && (
        <section className="panel" aria-label="粘贴到终端">
          <p>
            浏览器无法直接读取剪贴板。请在下方按 Ctrl+V（Mac 使用
            ⌘V），确认内容后发送到终端。
          </p>
          <label>
            粘贴内容
            <textarea
              ref={pasteInput}
              autoFocus
              rows={5}
              value={pasteText}
              onChange={(event) => setPasteText(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Escape") {
                  event.preventDefault();
                  event.stopPropagation();
                  closePaste();
                  setMessage("已取消粘贴");
                }
              }}
            />
          </label>
          <p className="muted">
            内容会发送到终端；包含换行时可能立即执行命令。
          </p>
          <div className="actions">
            <button
              type="button"
              className="primary"
              disabled={!pasteText}
              onClick={() => {
                if (!terminal.current || !pasteText) return;
                terminal.current.paste(pasteText);
                closePaste();
                setMessage("已粘贴到终端");
              }}
            >
              发送到终端
            </button>
            <button
              type="button"
              onClick={() => {
                closePaste();
                setMessage("已取消粘贴");
              }}
            >
              取消粘贴
            </button>
          </div>
        </section>
      )}
      <div
        className="remote-terminal"
        aria-label="SSH 交互终端"
        ref={container}
      />
    </>
  );
}
