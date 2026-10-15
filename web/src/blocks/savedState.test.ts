import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fenceNumber } from "./SavedPlace";
import { loadReply, readTicks, saveSoon, saveWaitingNow, ticksAfterLoad, toggleTick } from "./savedState";

const reply = { sessionId: "chat-2026-10-11", messageKey: "3f2b9c1e" };

describe("ticks", () => {
  it("a tap ticks or unticks one item, keeping them in order", () => {
    expect(toggleTick([0, 3], 2)).toEqual([0, 2, 3]);
    expect(toggleTick([0, 3], 3)).toEqual([0]);
    expect(toggleTick([], 0)).toEqual([0]);
  });
  it("reads saved ticks for a checklist of a given size, and nothing usable as null", () => {
    expect(readTicks([3, 0, 3], 5)).toEqual([0, 3]);
    expect(readTicks([0, 9, -1, 1.5, "2"], 5)).toEqual([0]);
    expect(readTicks("yes", 5)).toBeNull();
    expect(readTicks(undefined, 5)).toBeNull();
  });
  it("after loading: saved ticks win until the user taps; taps made meanwhile are kept and saved", () => {
    expect(ticksAfterLoad([1, 2], [0], false)).toEqual({ show: [1, 2], save: false });
    expect(ticksAfterLoad(null, [0], false)).toEqual({ show: [0], save: false });
    expect(ticksAfterLoad([1], [0, 1, 4], true)).toEqual({ show: [0, 1, 4], save: true });
  });
});

describe("saving and loading a reply's ticks", () => {
  let calls: { url: string; init?: RequestInit }[];
  beforeEach(() => {
    calls = [];
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      return new Response(JSON.stringify({ values: { "0/2": [1], "0/5": [0] } }), { status: 200 });
    }));
  });
  afterEach(() => {
    saveWaitingNow();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("sends only the last of a quick run of taps, a moment later", async () => {
    saveSoon(reply, "0/2", [0]);
    saveSoon(reply, "0/2", [0, 1]);
    saveSoon(reply, "0/2", [0, 1, 2]);
    expect(calls).toEqual([]);
    await vi.advanceTimersByTimeAsync(500);
    expect(calls.length).toBe(1);
    expect(calls[0].url).toBe("/api/block-state");
    expect(calls[0].init?.method).toBe("PUT");
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({ session_id: "chat-2026-10-11", message_key: "3f2b9c1e", block_path: "0/2", value: [0, 1, 2] });
  });
  it("keeps each block's own save", async () => {
    saveSoon(reply, "0/2", [0]);
    saveSoon(reply, "1/0.children.1", [3]);
    await vi.advanceTimersByTimeAsync(500);
    expect(calls.map((c) => JSON.parse(String(c.init?.body)).block_path).sort()).toEqual(["0/2", "1/0.children.1"]);
  });
  it("loads a reply's values, with a tap not sent yet winning over the server's", async () => {
    saveSoon(reply, "0/2", [0, 1, 2]);
    const values = await loadReply(reply);
    expect(calls[0].url).toBe("/api/block-state?session_id=chat-2026-10-11&message_key=3f2b9c1e");
    expect(values).toEqual({ "0/2": [0, 1, 2], "0/5": [0] });
  });
  it("a tap in another reply doesn't leak into this one", async () => {
    saveSoon({ sessionId: "chat-2026-10-11", messageKey: "other" }, "0/2", [4]);
    expect(await loadReply(reply)).toEqual({ "0/2": [1], "0/5": [0] });
  });
  it("sends what is waiting at once when the app goes to the background", () => {
    saveSoon(reply, "0/2", [7]);
    saveWaitingNow();
    expect(calls.length).toBe(1);
  });
});

describe("which fence of a reply", () => {
  const text = "Intro\n```odie-blocks\n[]\n```\nMore\n```json\n{}\n```\n```odie-blocks\n[]\n```\n";
  it("counts the blocks fences before the one at the offset", () => {
    expect(fenceNumber(text, text.indexOf("```odie-blocks"))).toBe(0);
    expect(fenceNumber(text, text.lastIndexOf("```odie-blocks"))).toBe(1);
  });
  it("counts an indented fence (in a list) too", () => {
    const listed = "- a\n  ```odie-blocks\n  []\n  ```\n- b\n  ```odie-blocks\n  []\n  ```";
    expect(fenceNumber(listed, listed.lastIndexOf("```odie-blocks"))).toBe(1);
  });
});
