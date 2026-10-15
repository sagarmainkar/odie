import { describe, expect, it } from "vitest";
import { deckLine, step, swipe, visible } from "./deck";
import type { Media } from "./media";

const page = (i: number) => ({ thumb: `t${i}`, view: `v${i}` });
const m = (deck: Media["deck"]): Media => ({ id: "1", kind: "file", title: "x", mime: "application/pdf", size: 1, created: 0, deck });

describe("deck", () => {
  it("says what it is", () => {
    expect(deckLine(m({ slides: 9, theme: "editorial", pages: [] }))).toBe("9 slides · Editorial");
    expect(deckLine(m({ slides: 1, theme: "warm", pages: [] }))).toBe("1 slide · Warm");
  });
  it("shows up to 10 previews, then a count", () => {
    expect(visible(Array.from({ length: 12 }, (_, i) => page(i))).more).toBe(2);
    expect(visible(Array.from({ length: 12 }, (_, i) => page(i))).shown).toHaveLength(10);
    expect(visible(Array.from({ length: 4 }, (_, i) => page(i)))).toEqual({ shown: [page(0), page(1), page(2), page(3)], more: 0 });
  });
  it("steps and swipes within the deck", () => {
    expect(step(0, -1, 9)).toBe(0);
    expect(step(8, 1, 9)).toBe(8);
    expect(step(3, 1, 9)).toBe(4);
    expect(swipe(-80, 10)).toBe(1);
    expect(swipe(80, 10)).toBe(-1);
    expect(swipe(30, 5)).toBe(0);
    expect(swipe(60, 90)).toBe(0);
  });
});

import { clampPan, pinchScale } from "./deck";

describe("zoom", () => {
  it("pinches between 1x and 4x", () => {
    expect(pinchScale(1, 100, 200)).toBe(2);
    expect(pinchScale(2, 100, 50)).toBe(1);
    expect(pinchScale(1, 100, 40)).toBe(1);
    expect(pinchScale(3, 100, 300)).toBe(4);
    expect(pinchScale(1, 0, 100)).toBe(1);  // no distance yet: unchanged
  });
  it("keeps a zoomed slide's edges on screen", () => {
    expect(clampPan(500, -500, 2, 400, 225)).toEqual({ x: 200, y: -112.5 });
    expect(clampPan(30, 10, 2, 400, 225)).toEqual({ x: 30, y: 10 });
    expect(clampPan(30, 10, 1, 400, 225)).toEqual({ x: 0, y: 0 });
  });
});
