import { useEffect } from "react";

export type LiveEvent = { type: "ping" } | { type: "message"; text: string; ts: number; session_id: string } | { type: "task"; id: number; status: string; until?: string }
  | { type: "thinking"; session_id: string; on: boolean };  // a chat's Think harder changed, in any app

/** One live connection to /api/events that reconnects after errors. Returns stop(). */
export function connectLive(make: () => EventSource, onEvent: (e: LiveEvent) => void, onReconnect?: () => void): () => void {
  let es: EventSource | null = null;
  let stopped = false;
  let wasOpen = false;
  let retry: ReturnType<typeof setTimeout> | null = null;
  const open = () => {
    retry = null;
    if (stopped) return;
    es = make();
    es.onopen = () => { if (wasOpen) onReconnect?.(); wasOpen = true; };
    es.onmessage = (m) => { try { const e = JSON.parse(m.data) as LiveEvent; if (e.type !== "ping") onEvent(e); } catch { /* ignore */ } };
    // A retry left pending after stop() used to open an orphan connection that delivered every event again.
    es.onerror = () => { es?.close(); if (!stopped && retry === null) retry = setTimeout(open, 3000); };
  };
  open();
  return () => { stopped = true; if (retry !== null) clearTimeout(retry); es?.close(); };
}

/** Subscribe to /api/events (SSE). Reconnects automatically; the handler sees every non-ping event. */
export function useLive(onEvent: (e: LiveEvent) => void, onReconnect?: () => void) {
  useEffect(() => {
    const stop = connectLive(() => new EventSource("/api/events"), onEvent, onReconnect);
    const onVisible = () => { if (document.visibilityState === "visible") onReconnect?.(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => { stop(); document.removeEventListener("visibilitychange", onVisible); };
  }, [onEvent, onReconnect]);
}
