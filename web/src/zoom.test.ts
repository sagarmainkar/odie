import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// Pinch-zoom on the phone (14 Oct 2026): the viewport once said maximum-scale=1, which switches pinching off for the
// whole app, so a table or chart that came out small could not be read. Zoom stays on; inputs stay 16px on touch
// screens so iOS does not jump into them on focus.
describe("the page lets the phone pinch-zoom", () => {
  const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
  const css = readFileSync(new URL("./styles.css", import.meta.url), "utf8");
  it("has no maximum-scale or user-scalable=no in the viewport", () => {
    const viewport = /<meta name="viewport" content="([^"]*)"/.exec(html)![1];
    expect(viewport).not.toMatch(/maximum-scale|user-scalable=no/);
    expect(viewport).toContain("width=device-width");
  });
  it("keeps inputs at 16px on touch screens", () => {
    expect(css).toMatch(/@media \(pointer: coarse\)[^}]*input[^}]*font-size: max\(16px, 1em\)/);
  });
});
