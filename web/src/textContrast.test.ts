import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// Secondary text has to be readable in the three light themes (design review, 17 Nov 2026). Muted text (times,
// descriptions, labels at 12-13.5px) needs 4.5:1, the WCAG level for small text; dim text (hints, markers) needs at
// least 3:1. Both are measured on a white card and on each light ground. Night has its own values and stays as it is.
const css = readFileSync(new URL("./styles.css", import.meta.url), "utf8");

// The text of the first rule whose selector is exactly `selector`, e.g. ':root[data-tod="noon"]' -> its body.
// The stylesheet lines selectors up with spaces, so any run of spaces may stand before the brace.
function ruleBody(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const found = new RegExp(`^${escaped}\\s*\\{([^}]*)\\}`, "m").exec(css);
  if (!found) throw new Error(`no rule ${selector}`);
  return found[1];
}

// One token's colour in a rule body, e.g. ('--t-muted', '... --t-muted: #85828F; ...') -> '#85828F'.
function token(name: string, body: string): string {
  const found = new RegExp(`${name}:\\s*(#[0-9A-Fa-f]{6})`).exec(body);
  if (!found) throw new Error(`no ${name}`);
  return found[1];
}

// WCAG relative luminance of '#RRGGBB'.
function luminance(hex: string): number {
  const channels = [1, 3, 5].map((at) => parseInt(hex.slice(at, at + 2), 16) / 255);
  const linear = channels.map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

// WCAG contrast ratio between two colours, e.g. ('#000000', '#FFFFFF') -> 21.
function contrast(a: string, b: string): number {
  const lighter = Math.max(luminance(a), luminance(b));
  const darker = Math.min(luminance(a), luminance(b));
  return (lighter + 0.05) / (darker + 0.05);
}

const day = ruleBody(":root");
const lightBackgrounds = {
  "white card": "#FFFFFF",
  "dawn ground": token("--t-ground", day),
  "noon ground": token("--t-ground", ruleBody(':root[data-tod="noon"]')),
  "evening ground": token("--t-ground", ruleBody(':root[data-tod="evening"]')),
};

describe("secondary text is readable in the light themes", () => {
  it("reads the grounds the review measured", () => {
    expect(Object.values(lightBackgrounds)).toEqual(["#FFFFFF", "#F7F3EE", "#F3F5F9", "#F6F1F0"]);
  });
  for (const [where, background] of Object.entries(lightBackgrounds)) {
    it(`muted text reaches 4.5:1 on the ${where}`, () => {
      expect(contrast(token("--t-muted", day), background)).toBeGreaterThanOrEqual(4.5);
    });
    it(`dim text reaches 3:1 on the ${where}`, () => {
      expect(contrast(token("--t-dim", day), background)).toBeGreaterThanOrEqual(3);
    });
  }
  it("leaves night's muted and dim as they were", () => {
    const night = ruleBody(':root[data-tod="night"]');
    expect(token("--t-muted", night)).toBe("#9A96AA");
    expect(token("--t-dim", night)).toBe("#6F6B80");
  });
});
