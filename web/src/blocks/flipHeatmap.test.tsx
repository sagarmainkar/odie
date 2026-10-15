import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Blocks } from "./Blocks";
import { cellColour, cellText, rangeOf } from "./heatmapColour";
import { parseBlocks } from "./parse";
import { scaleOf } from "./parse/heatmap";

function draw(json: unknown): string {
  const code = JSON.stringify(json);
  return renderToStaticMarkup(<Blocks blocks={parseBlocks(code)!} source={code} />);
}

describe("reading a flip block", () => {
  it("keeps cards with a front and a back, takes question/answer as aliases, drops the rest", () => {
    const b = parseBlocks(JSON.stringify([{ type: "flip", title: "Asian Games", cards: [
      { front: "Most golds?", back: "China · 201", image: "https://x.test/cn.jpg" },
      { question: "Host city?", answer: "Nagoya" },
      { front: "No answer" },
      { back: "No question" },
      { front: "Bad photo", back: "x", image: "http://x.test/a.jpg" },
    ] }]))!;
    const f = b[0] as any;
    expect(f.type).toBe("flip");
    expect(f.title).toBe("Asian Games");
    expect(f.cards).toEqual([
      { front: "Most golds?", back: "China · 201", image: "https://x.test/cn.jpg" },
      { front: "Host city?", back: "Nagoya" },
      { front: "Bad photo", back: "x" },
    ]);
  });
  it("drops a flip with no usable card, and keeps at most 12", () => {
    expect(parseBlocks(JSON.stringify([{ type: "flip", cards: [{ front: "only" }] }]))).toEqual([]);
    const many = Array.from({ length: 15 }, (_, i) => ({ front: `q${i}`, back: `a${i}` }));
    const f = parseBlocks(JSON.stringify([{ type: "flip", cards: many }]))![0] as any;
    expect(f.cards.length).toBe(12);
  });
});

describe("reading a heatmap block", () => {
  it("pairs row labels with value rows, drops short rows, infers the scale", () => {
    const b = parseBlocks(JSON.stringify([{ type: "heatmap", title: "Finance", rows: ["JPM", "GS", "MS"], cols: ["Q1", "Q2"],
      values: [[4.1, -1.2], [7.5], [1.4, "n/a", 9]], unit: "%" }]))!;
    const h = b[0] as any;
    expect(h.rows).toEqual(["JPM", "MS"]);
    expect(h.values).toEqual([[4.1, -1.2], [1.4, null]]);
    expect(h.cols).toEqual(["Q1", "Q2"]);
    expect(h.unit).toBe("%");
    expect(h.scale).toBe("diverging");
  });
  it("drops a heatmap without rows, cols or values", () => {
    expect(parseBlocks(JSON.stringify([{ type: "heatmap", rows: ["a"], cols: [], values: [[1]] }]))).toEqual([]);
    expect(parseBlocks(JSON.stringify([{ type: "heatmap", rows: ["a"], cols: ["x"], values: [[]] }]))).toEqual([]);
  });
  it("takes the scale the model asks for, else diverging only when a value is negative", () => {
    expect(scaleOf("sequential", [[-1, 2]])).toBe("sequential");
    expect(scaleOf(undefined, [[-1, 2]])).toBe("diverging");
    expect(scaleOf(undefined, [[1, 2]])).toBe("sequential");
    expect(scaleOf("rainbow", [[1, null]])).toBe("sequential");
  });
});

describe("a heatmap cell's colour and text", () => {
  const range = { low: -10, high: 10 };
  it("finds the range, skipping blanks", () => {
    expect(rangeOf([[4, -1], [null, 7]])).toEqual({ low: -1, high: 7 });
    expect(rangeOf([[null]])).toEqual({ low: 0, high: 0 });
  });
  it("shades losses red and gains green, deeper the bigger, on a diverging scale", () => {
    expect(cellColour(-10, range, "diverging")).toBe("color-mix(in srgb, var(--t-chart-8) 85%, transparent)");
    expect(cellColour(10, range, "diverging")).toBe("color-mix(in srgb, var(--t-chart-3) 85%, transparent)");
    expect(cellColour(5, range, "diverging")).toBe("color-mix(in srgb, var(--t-chart-3) 48%, transparent)");
    expect(cellColour(0, range, "diverging")).toBe("color-mix(in srgb, var(--t-chart-3) 10%, transparent)");
    expect(cellColour(null, range, "diverging")).toBe("var(--t-well)");
  });
  it("shades one blue light to dark on a sequential scale", () => {
    expect(cellColour(-10, range, "sequential")).toBe("color-mix(in srgb, var(--t-chart-1) 10%, transparent)");
    expect(cellColour(10, range, "sequential")).toBe("color-mix(in srgb, var(--t-chart-1) 85%, transparent)");
    expect(cellColour(3, { low: 3, high: 3 }, "sequential")).toBe("color-mix(in srgb, var(--t-chart-1) 85%, transparent)");
  });
  it("prints a number short, with its unit", () => {
    expect(cellText(4.125, "%")).toBe("4.1%");
    expect(cellText(7)).toBe("7");
    expect(cellText(2.5, "h")).toBe("2.5 h");
    expect(cellText(null, "%")).toBe("–");
  });
});

describe("drawing them", () => {
  it("draws flip cards with the front showing and the back behind it", () => {
    const html = draw([{ type: "flip", title: "Quiz", cards: [{ front: "Most golds?", back: "China · 201" }, { front: "Host?", back: "Nagoya", image: "https://x.test/n.jpg" }] }]);
    expect(html).toContain("Quiz");
    expect(html).toContain("Most golds?");
    expect(html).toContain("China · 201");
    expect(html).toContain('aria-pressed="false"');
    expect(html).toContain("1 / 2");
    expect(html).toContain('src="https://x.test/n.jpg"');
    expect(html).not.toContain("is-turned");
  });
  it("draws a heatmap with numbers in the cells when there are few columns, and none when there are many", () => {
    const few = draw([{ type: "heatmap", rows: ["JPM"], cols: ["Q1", "Q2"], values: [[4.1, -1.2]], unit: "%" }]);
    expect(few).toContain(">4.1%<");
    expect(few).toContain("var(--t-chart-8)");  // the loss
    expect(few).toContain('role="rowheader"');
    const cols = Array.from({ length: 8 }, (_, i) => `M${i + 1}`);
    const many = draw([{ type: "heatmap", rows: ["JPM"], cols, values: [cols.map((_, i) => i)] }]);
    expect(many).not.toContain(">7<");
    expect(many).toContain('aria-label="JPM, M8: 7"');  // still there for a screen reader and the tap
  });
});
