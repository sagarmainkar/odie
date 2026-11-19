import { afterEach, describe, expect, it, vi } from "vitest";
import { everyday, followsPick, getPick, settlePick, withPickOf } from "./pick";

afterEach(() => { vi.unstubAllGlobals(); });

describe("withPickOf", () => {
  it("names the picked personality on the calls that mean something else for each one", () => {
    expect(withPickOf("/api/threads?q=x", "abc")).toBe("/api/threads?q=x&personality=abc");
    expect(withPickOf("/api/history?date=2026-11-17", "abc")).toBe("/api/history?date=2026-11-17&personality=abc");
    expect(withPickOf("/api/chat", "abc")).toBe("/api/chat?personality=abc");
    expect(followsPick("/api/approvals/7/decide")).toBe(true);
    expect(followsPick("/api/chat/thinking")).toBe(true);
  });

  it("leaves a call alone while everyday Odie is picked, unless the call always says who", () => {
    expect(withPickOf("/api/threads?q=x", "")).toBe("/api/threads?q=x");
    expect(withPickOf("/api/events", "", true)).toBe("/api/events?personality=");
    expect(withPickOf("/api/events", "abc", true)).toBe("/api/events?personality=abc");
  });

  it("leaves the calls that are the same for everyone alone", () => {
    expect(withPickOf("/api/tasks", "abc")).toBe("/api/tasks");
    expect(withPickOf("/api/persona", "abc")).toBe("/api/persona");  // Odie's own name and picture, for Today and the rest
    expect(withPickOf("/api/persona", "abc", true)).toBe("/api/persona?personality=abc");  // Settings asks for the picked one's
    expect(followsPick("/api/watch")).toBe(true);  // each one's own watch (Pulse)
    expect(followsPick("/api/chats")).toBe(false);  // only the path itself or what is under it
  });

  it("lets an everyday screen ask for everyday Odie's, whoever is picked", () => {
    expect(everyday("/api/approvals")).toBe("/api/approvals?personality=");  // Today and the Ask bar: Odie's cards
    expect(withPickOf(everyday("/api/approvals"), "abc")).toBe("/api/approvals?personality=");  // the pick is not added on top
  });

  it("never names it twice", () => {
    expect(withPickOf("/api/soul?personality=abc", "abc", true)).toBe("/api/soul?personality=abc");
  });
});

describe("settlePick", () => {
  it("falls back to Odie when the picked personality no longer exists", () => {
    expect(settlePick("gone", ["abc"])).toBe("");
    expect(settlePick("abc", ["abc"])).toBe("abc");
    expect(settlePick("", ["abc"])).toBe("");
  });
});

describe("getPick", () => {
  it("is Odie when there is no storage, or it can't be read", () => {
    expect(getPick()).toBe("");
    vi.stubGlobal("localStorage", { getItem() { throw new Error("blocked"); } });
    expect(getPick()).toBe("");
  });

  it("is what was saved", () => {
    vi.stubGlobal("localStorage", { getItem: (key: string) => (key === "odie:personality" ? "abc" : null) });
    expect(getPick()).toBe("abc");
  });
});
