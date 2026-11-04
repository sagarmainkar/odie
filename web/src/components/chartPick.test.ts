// Picking a chart's point or row (chartPick.ts): when leaving clears the hover card.
import { describe, expect, it } from "vitest";
import { clearsOnLeave } from "./chartPick";

describe("clearsOnLeave", () => {
  it("clears the card when a mouse leaves, and keeps it after a finger or pen lifts", () => {
    expect(clearsOnLeave("mouse")).toBe(true);
    expect(clearsOnLeave("touch")).toBe(false);
    expect(clearsOnLeave("pen")).toBe(false);
  });
});
