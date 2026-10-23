import { describe, expect, it } from "vitest";
import { badgeTone, chatRunHash, tileColour } from "./needs";

describe("needs", () => {
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
    expect(chatRunHash("Show the draft for desk item mail:r1")).toBe("#chat?run=Show%20the%20draft%20for%20desk%20item%20mail%3Ar1");
  });
});
