import { describe, expect, it } from "vitest";
import { askedFromHash, composerHeight, runFromHash } from "./Chat";

describe("composerHeight", () => {
  it("grows from one to five lines", () => {
    expect(composerHeight(34)).toBe("34px");
    expect(composerHeight(400)).toBe("114px");
  });
  it("leaves the height alone while Chat is hidden (nothing to measure)", () => {
    expect(composerHeight(0)).toBe("");
  });
});

describe("askedFromHash", () => {
  it("reads a question handed over from Today", () => {
    expect(askedFromHash("#chat?q=What%27s%20on%20Thursday%3F")).toBe("What's on Thursday?");
  });
  it("ignores plain chat and other screens", () => {
    expect(askedFromHash("#chat")).toBeNull();
    expect(askedFromHash("#today")).toBeNull();
  });
});

describe("a new chat starts clean", () => {
  it("shows only what comes after the last /new", async () => {
    const { afterLastNewChat } = await import("./Chat");
    const m = (role: string, text: string) => ({ role, text });
    const items = [m("user", "old question"), m("odie", "old answer"), m("odie", "(New chat.)"), m("user", "fresh"), m("odie", "reply")];
    expect(afterLastNewChat(items)).toEqual({ items: [m("user", "fresh"), m("odie", "reply")], cut: true });
    expect(afterLastNewChat([m("user", "a"), m("odie", "(New chat.)")])).toEqual({ items: [], cut: true });
    expect(afterLastNewChat([m("user", "a")])).toEqual({ items: [m("user", "a")], cut: false });
  });
});

describe("runFromHash", () => {
  it("reads the request a Today card's button sends", () => {
    expect(runFromHash("#chat?run=Show%20the%20draft%20for%20watch%20item%20mail%3Ar1")).toBe("Show the draft for watch item mail:r1");
    expect(runFromHash("#chat?q=hello")).toBeNull();
  });
});
