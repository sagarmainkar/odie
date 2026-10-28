import { afterEach, describe, expect, it, vi } from "vitest";
import { loadThinking, saveThinking, thinkingAfter } from "./thinking";

afterEach(() => vi.unstubAllGlobals());

function answering(body: unknown) {
  const fetch = vi.fn(async (_url: string, _init?: RequestInit) => new Response(JSON.stringify(body), { status: 200 }));
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

describe("the chat's Think harder from Odie", () => {
  it("asks for today's chat, or a thread by its id", async () => {
    const fetch = answering({ session_id: "chat-2026-10-28", on: true });
    expect(await loadThinking()).toEqual({ session_id: "chat-2026-10-28", on: true });
    expect(fetch.mock.calls[0][0]).toBe("/api/chat/thinking");
    await loadThinking("chat-2026-10-20-2");
    expect(fetch.mock.calls[1][0]).toBe("/api/chat/thinking?session_id=chat-2026-10-20-2");
  });

  it("saves a flip with PUT, naming the chat", async () => {
    const fetch = answering({ session_id: "chat-2026-10-28", on: false });
    expect(await saveThinking(false, "chat-2026-10-28")).toEqual({ session_id: "chat-2026-10-28", on: false });
    const [url, init] = fetch.mock.calls[0];
    expect(url).toBe("/api/chat/thinking");
    expect(init?.method).toBe("PUT");
    expect(JSON.parse(String(init?.body))).toEqual({ session_id: "chat-2026-10-28", on: false });
  });

  it("fails loudly to the caller only (the chat keeps what it showed)", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("no", { status: 500 })));
    await expect(saveThinking(true)).rejects.toThrow("HTTP 500");
  });
});

describe("a live change", () => {
  const shown = { session_id: "chat-2026-10-28", on: false };

  it("applies to the chat on screen", () => {
    expect(thinkingAfter(shown, { type: "thinking", session_id: "chat-2026-10-28", on: true })).toEqual({ session_id: "chat-2026-10-28", on: true });
  });

  it("leaves it alone for another chat, another kind of event, or before the chat is known", () => {
    expect(thinkingAfter(shown, { type: "thinking", session_id: "chat-2026-10-27", on: true })).toBe(shown);
    expect(thinkingAfter(shown, { type: "message", session_id: "chat-2026-10-28" })).toBe(shown);
    expect(thinkingAfter(null, { type: "thinking", session_id: "chat-2026-10-28", on: true })).toBeNull();
  });
});

describe("a chat turn", () => {
  it("doesn't send Think harder: Odie uses the chat's own", async () => {
    const fetch = vi.fn(async (_url: string, _init?: RequestInit) => new Response("data: {\"type\": \"done\", \"text\": \"ok\"}\n\n", { status: 200 }));
    vi.stubGlobal("fetch", fetch);
    const { streamChat } = await import("./sse");
    for await (const _ of streamChat("hi", [], "chat-2026-10-28")) { /* read it all */ }
    expect(JSON.parse(String(fetch.mock.calls[0][1]?.body))).toEqual({ text: "hi", images: [], session_id: "chat-2026-10-28" });
  });
});
