import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import type { RemoteRequest, RemoteSession, StreamText } from "./types";
const completed = new Set(["succeeded", "failed", "closed", "interrupted"]);
export function useRemoteSession(
  callbacks: {
    onResult?: (session: RemoteSession) => void;
    onText?: (event: StreamText) => void;
    onOpen?: () => void;
  } = {},
) {
  const [session, setSession] = useState<RemoteSession>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [connected, setConnected] = useState(false);
  const handlers = useRef(callbacks);
  handlers.current = callbacks;
  const current = useRef<RemoteSession | undefined>(undefined);
  const generation = useRef(0);
  const live = useRef(true);
  const socket = useRef<WebSocket | undefined>(undefined);
  const poll = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const heartbeat = useRef<ReturnType<typeof setInterval> | undefined>(
    undefined,
  );
  const release = useCallback(() => {
    generation.current++;
    clearTimeout(poll.current);
    clearInterval(heartbeat.current);
    const ws = socket.current;
    socket.current = undefined;
    if (ws) {
      ws.onclose = null;
      ws.onerror = null;
      ws.onmessage = null;
      ws.onopen = null;
      ws.close();
    }
    const row = current.current;
    current.current = undefined;
    if (row)
      void api(
        `/remote-sessions/${encodeURIComponent(row.id)}`,
        "DELETE",
        undefined,
        { keepalive: true },
      ).catch(() => {});
  }, []);
  const close = useCallback(() => {
    release();
    if (live.current) {
      setConnected(false);
      setBusy(false);
      setSession((row) => (row ? { ...row, state: "closed" } : row));
    }
  }, [release]);
  useEffect(() => {
    live.current = true;
    window.addEventListener("pagehide", close);
    return () => {
      live.current = false;
      window.removeEventListener("pagehide", close);
      release();
    };
  }, [release, close]);
  const send = useCallback(
    (message: Record<string, unknown>) => {
      if (socket.current?.readyState !== WebSocket.OPEN) return false;
      // Do not let pasted input grow an unbounded WebSocket send queue.
      if (socket.current.bufferedAmount > 1024 * 1024) {
        setError("发送速度不足，连接已断开。请主动重新连接。");
        close();
        return false;
      }
      socket.current.send(JSON.stringify(message));
      return true;
    },
    [close],
  );
  const accept = useCallback(
    function accept(row: RemoteSession, token: number) {
      if (!live.current || generation.current !== token) return;
      current.current = row;
      setSession(row);
      setBusy(false);
      if (completed.has(row.state)) {
        if (row.state === "succeeded") handlers.current.onResult?.(row);
        else if (row.state === "failed" || row.state === "interrupted")
          setError(row.message || row.error_code || "远程会话已中断");
        return;
      }
      if (row.state === "needs_password" || row.state === "needs_trust") return;
      if (
        (row.state === "ready" || row.state === "running") &&
        (row.kind === "terminal" || row.kind === "log-follow")
      ) {
        const url = new URL(
          `/api/v1/remote-sessions/${encodeURIComponent(row.id)}/stream`,
          window.location.href,
        );
        url.protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        const ws = new WebSocket(url);
        socket.current = ws;
        ws.onopen = () => {
          if (generation.current !== token) {
            ws.close();
            return;
          }
          setConnected(true);
          setSession({ ...row, state: "running" });
          handlers.current.onOpen?.();
          heartbeat.current = setInterval(() => {
            if (ws.readyState === WebSocket.OPEN)
              ws.send(JSON.stringify({ type: "heartbeat" }));
          }, 20000);
        };
        ws.onmessage = (event) => {
          if (generation.current !== token) return;
          try {
            const message = JSON.parse(event.data);
            if (message.type === "text" && typeof message.text === "string")
              handlers.current.onText?.(message);
            else if (message.type === "error") {
              setError(message.message || message.code || "远程连接失败");
              close();
            } else if (message.type === "closed") {
              setError(
                message.reason ? `连接已结束：${message.reason}` : "连接已结束",
              );
              close();
            }
          } catch {
            setError("收到无法识别的远程消息，连接已断开");
            close();
          }
        };
        ws.onerror = () => {
          if (generation.current === token) {
            setError("连接失败，请检查网络后主动重试。");
            close();
          }
        };
        ws.onclose = () => {
          if (generation.current === token) {
            setError("连接已断开；不会自动重连或重放输入。");
            close();
          }
        };
        return;
      }
      poll.current = setTimeout(() => {
        api<RemoteSession>(`/remote-sessions/${encodeURIComponent(row.id)}`)
          .then((next) => accept(next, token))
          .catch((e) => {
            if (generation.current === token && live.current) {
              setError(e.message);
              close();
            }
          });
      }, 750);
    },
    [close],
  );
  const start = useCallback(
    async (request: RemoteRequest) => {
      release();
      const token = generation.current;
      setSession(undefined);
      setConnected(false);
      setError("");
      setBusy(true);
      try {
        const row = await api<RemoteSession>(
          "/remote-sessions",
          "POST",
          request,
        );
        if (!live.current || generation.current !== token) {
          void api(
            `/remote-sessions/${encodeURIComponent(row.id)}`,
            "DELETE",
            undefined,
            { keepalive: true },
          ).catch(() => {});
          return;
        }
        accept(row, token);
      } catch (e) {
        if (live.current && generation.current === token) {
          setError((e as Error).message);
          setBusy(false);
        }
      }
    },
    [release, accept],
  );
  const authenticate = useCallback(
    async (password: string) => {
      const row = current.current;
      if (!row?.challenge || row.state !== "needs_password") return;
      const token = generation.current;
      setBusy(true);
      setError("");
      try {
        accept(
          await api<RemoteSession>(
            `/remote-sessions/${encodeURIComponent(row.id)}/authenticate`,
            "POST",
            { challenge: row.challenge, password },
          ),
          token,
        );
      } catch (e) {
        if (live.current && generation.current === token) {
          setError((e as Error).message);
          setBusy(false);
        }
      }
    },
    [accept],
  );
  const active = busy || (!!session && !completed.has(session.state));
  return {
    session,
    busy,
    error,
    connected,
    active,
    start,
    close,
    send,
    authenticate,
  };
}
export type RemoteController = ReturnType<typeof useRemoteSession>;
