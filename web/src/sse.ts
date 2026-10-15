import type { ReplyUsage } from "./usage";

export type ChatEvent =
  | { type: "token"; text: string; key?: string; session_id?: string }  // key, session_id: the reply's name (see Chat's Msg)
  | { type: "text"; text: string; key?: string; session_id?: string; usage?: ReplyUsage }  // usage: the finished reply's counts
  | { type: "tool_start"; tool: string; args: Record<string, unknown> }
  | { type: "tool_done"; tool: string }
  | { type: "done"; text: string }
  | { type: "error"; message: string }
  | { type: string; [k: string]: unknown };

export function parseSseLines(buffer: string): { events: ChatEvent[]; rest: string } {
  const events: ChatEvent[] = [];
  buffer = buffer.replace(/\r\n/g, "\n");
  let idx: number;
  while ((idx = buffer.indexOf("\n\n")) >= 0) {
    const block = buffer.slice(0, idx);
    buffer = buffer.slice(idx + 2);
    const data = block.split("\n").filter((l) => l.startsWith("data: ")).map((l) => l.slice(6)).join("\n");
    if (data) {
      try { events.push(JSON.parse(data)); } catch { /* partial or malformed: skip */ }
    }
  }
  return { events, rest: buffer };
}

export async function* streamChat(text: string, thinking = false, images: string[] = [], sessionId?: string, signal?: AbortSignal): AsyncGenerator<ChatEvent> {
  const res = await fetch("/api/chat", {
    method: "POST", headers: { "Content-Type": "application/json" }, signal,
    body: JSON.stringify({ text, thinking, images, ...(sessionId ? { session_id: sessionId } : {}) }),
  });
  if (!res.ok || !res.body) { yield { type: "error", message: `HTTP ${res.status}` }; return; }
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const { events, rest } = parseSseLines(buf);
    buf = rest;
    for (const e of events) yield e;
  }
}
