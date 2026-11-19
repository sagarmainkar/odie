import { describe, expect, it } from "vitest";
import { badgeTone, busyWord, buttonsOf, chatRunHash, knowsAction, menuItems, opensSafely, tileColour, type Need, type NeedAction } from "./needs";

describe("needs", () => {
  it("lists a card's buttons as the move, Done and Later, or two from an older server", () => {
    const need: Need = { ref: "mail:r1", title: "Reply", why: "", icon: "mail", badge: "", ask: "",
      main: { label: "Show the draft", action: "chat", value: "x" }, other: { label: "Done", action: "dismiss", value: "mail:r1" },
      later: { label: "Later", action: "later", value: "mail:r1" } };
    expect(buttonsOf(need).map((b) => b.label)).toEqual(["Show the draft", "Done", "Later"]);
    expect(buttonsOf({ ...need, later: undefined }).map((b) => b.label)).toEqual(["Show the draft", "Done"]);
  });
  it("colours a card's tile by its icon", () => {
    expect(tileColour("rupee")).toBe("green");
    expect(tileColour("alert")).toBe("orange");
    expect(tileColour("photo")).toBe("ink");
  });
  it("warns only for overdue", () => {
    expect(badgeTone("Overdue")).toBe("warn");
    expect(badgeTone("30 Oct, 09:00")).toBe("soft");
  });
  it("sends a chat button's request through the hash", () => {
    expect(chatRunHash("Show the draft for watch item mail:r1")).toBe("#chat?run=Show%20the%20draft%20for%20watch%20item%20mail%3Ar1");
  });
});

describe("a card's open button", () => {
  it("opens only a GitHub page the server built", () => {
    expect(opensSafely("https://github.com/example/app/pull/49")).toBe(true);
    expect(opensSafely("https://github.com/example/app/issues/7")).toBe(true);
    expect(opensSafely("javascript:alert(1)")).toBe(false);
    expect(opensSafely("http://github.com/example/app/pull/49")).toBe(false);
    expect(opensSafely("https://github.com.evil.example/a/b/pull/1")).toBe(false);
  });
  it("knows phase 5's actions and keeps a menu to what it can carry out", () => {
    for (const a of ["quiet_accept", "learn_undo", "less_like_this", "forget"]) expect(knowsAction(a)).toBe(true);
    expect(busyWord("quiet_accept")).toBe("Saving…");
    const more: NeedAction[] = [{ label: "Split", action: "split", value: 3 }, { label: "Less like this", action: "less_like_this", value: 3 },
      { label: "Forget this", action: "forget", value: 3 }, { label: "Snooze", action: "snooze_loop" as NeedAction["action"], value: 3 }];
    expect(menuItems(more, 3).map((m) => m.action)).toEqual(["split", "less_like_this", "forget"]);
    expect(menuItems(more, 1).map((m) => m.action)).toEqual(["less_like_this", "forget"]);
    expect(menuItems(undefined, 3)).toEqual([]);
  });
});
