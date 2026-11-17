import { useEffect } from "react";
import { onPickChange, withPick } from "./pick";

export type LiveEvent = { type: "ping" } | { type: "message"; text: string; ts: number; session_id: string; personality?: string } | { type: "task"; id: number; status: string; until?: string }
  | { type: "thinking"; session_id: string; on: boolean }  // a chat's Think harder changed, in any app
  | { type: "elsewhere"; personality: string; what: "reply" | "card" };  // something waits in a personality that isn't on screen (no words)

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

type Listener = { onEvent: (e: LiveEvent) => void; onReconnect?: () => void };

/** One stream for the whole app, shared by every listener: opened with the first, closed with the last. A stream
 * each used to be one connection each: Today held five (the app, the chat, the reminder curtain, Today, Tracking), one
 * short of the six a browser allows a host over plain HTTP, after which every tap and fetch waits. `make` is for tests.
 *   subscribe(a), subscribe(b) -> one EventSource, both hear each event; both stop -> it closes. */
export function shareLive(make: () => EventSource) {
  const listeners = new Set<Listener>();
  let stop: (() => void) | null = null;
  const connect = () => connectLive(make, (e) => listeners.forEach((l) => l.onEvent(e)), () => listeners.forEach((l) => l.onReconnect?.()));
  function subscribe(listener: Listener): () => void {
    listeners.add(listener);
    if (stop === null) stop = connect();
    return () => {
      listeners.delete(listener);
      if (listeners.size === 0 && stop !== null) { stop(); stop = null; }
    };
  }
  /** Close the stream and open it again with the same listeners: `make` is called afresh, so a stream whose address
   *  says who the app is talking to follows a change of pick. Nobody listening -> nothing is opened. */
  subscribe.reopen = (): void => {
    if (stop === null) return;
    stop();
    stop = connect();
    listeners.forEach((l) => l.onReconnect?.());  // what happened between the two streams is read again
  };
  return subscribe;
}

// The stream always says who the app is talking to, even everyday Odie: an app that says nothing (the Mac app, the
// terminal) gets no personality's events at all, and one that says so hears when another personality has something.
const subscribeLive = shareLive(() => new EventSource(withPick("/api/events", true)));
onPickChange(() => subscribeLive.reopen());

/** Subscribe to /api/events (SSE), on the app's one shared stream. Reconnects automatically; the handler sees every
 * non-ping event. */
export function useLive(onEvent: (e: LiveEvent) => void, onReconnect?: () => void) {
  useEffect(() => {
    const stop = subscribeLive({ onEvent, onReconnect });
    const onVisible = () => { if (document.visibilityState === "visible") onReconnect?.(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => { stop(); document.removeEventListener("visibilitychange", onVisible); };
  }, [onEvent, onReconnect]);
}
