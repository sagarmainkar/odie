import { describe, expect, it } from "vitest";
import { belongsHere, groupThreads, type Thread } from "./threads";

const t = (o: Partial<Thread>): Thread => ({ id: "chat-2026-10-05", title: "x", renamed: false, date: "2026-10-05", messages: 2, started: 0, updated: 0, pinned: false, snippet: null, ...o });

describe("threads", () => {
  it("groups pinned, then by day", () => {
    const g = groupThreads([t({ id: "a", pinned: true, date: "2026-09-01" }), t({ id: "b" }), t({ id: "c", date: "2026-10-04" }),
      t({ id: "d", date: "2026-10-01" }), t({ id: "e", date: "2026-08-20" })], "2026-10-05");
    expect(g.map((x) => [x.label, x.items.map((i) => i.id)])).toEqual([
      ["Pinned", ["a"]], ["Today", ["b"]], ["Yesterday", ["c"]], ["This week", ["d"]], [g[4].label, ["e"]]]);
    expect(g[4].label).toMatch(/August 2026/);
  });
  it("keeps live messages in their own chat", () => {
    expect(belongsHere("chat-2026-10-05-2", null, "2026-10-05")).toBe(true);
    expect(belongsHere("chat-2026-10-02", null, "2026-10-05")).toBe(false);
    expect(belongsHere("chat-2026-10-02", "chat-2026-10-02", "2026-10-05")).toBe(true);
    expect(belongsHere("chat-2026-10-05", "chat-2026-10-02", "2026-10-05")).toBe(false);
    expect(belongsHere(undefined, null, "2026-10-05")).toBe(true);
  });
});
