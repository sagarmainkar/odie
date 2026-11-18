import { describe, expect, it } from "vitest";
import { badgeTone, buttonsOf, chatRunHash, tileColour, type Need } from "./needs";

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
