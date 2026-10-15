// The chart kinds added on 2026-10-12 (pie, donut, stacked, hbar, area, combo): their sums, how parseChart reads each
// one (as a model writes it, sloppily, and broken), and what each draws.
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { readBlocks } from "../blocks/parse";
import { ChartBlock, parseChart } from "./ChartBlock";
import { chartKind, chartScales, isOnRightScale, pieSlices, scaleFor, sharePct, stackSeries, totalAt, type ChartSpec } from "./chartData";

const chart = (json: unknown) => parseChart(JSON.stringify(json));
const draw = (spec: ChartSpec) => renderToStaticMarkup(<ChartBlock spec={spec} />);
const count = (html: string, tag: string) => (html.match(new RegExp(`<${tag}[ >]`, "g")) ?? []).length;

describe("chartKind", () => {
  it("knows every kind by name, in any case, and a few aliases; anything else is a line", () => {
    expect(["line", "bar", "area", "stacked", "hbar", "combo", "pie", "donut"].map(chartKind))
      .toEqual(["line", "bar", "area", "stacked", "hbar", "combo", "pie", "donut"]);
    expect(chartKind("Donut")).toBe("donut");
    expect(chartKind("doughnut")).toBe("donut");
    expect(chartKind("stacked_bar")).toBe("stacked");
    expect(chartKind("horizontal bar")).toBe("hbar");
    expect(chartKind("scatter")).toBe("line");
    expect(chartKind(undefined)).toBe("line");
  });
});

describe("pieSlices", () => {
  it("drops zero, negative and missing values", () => {
    expect(pieSlices(["Rent", "Food", "Fun", "Refund", "Gap"], [30000, 12000, 0, -500, null]))
      .toEqual({ x: ["Rent", "Food"], data: [30000, 12000] });
  });
  it("keeps the 7 biggest in their order past 8 slices, the rest one Other at the end", () => {
    const x = ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"];
    const out = pieSlices(x, [1, 10, 2, 9, 3, 8, 7, 6, 5, 4]);
    expect(out.x).toEqual(["b", "d", "f", "g", "h", "i", "j", "Other"]);
    expect(out.data).toEqual([10, 9, 8, 7, 6, 5, 4, 6]);
  });
  it("leaves exactly 8 slices alone", () => {
    expect(pieSlices(["a", "b", "c", "d", "e", "f", "g", "h"], [1, 2, 3, 4, 5, 6, 7, 8]).x).toHaveLength(8);
  });
});

describe("stacking", () => {
  it("piles positives up and negatives down from zero; a gap has no band and adds nothing", () => {
    expect(stackSeries([{ data: [10, 20, 5] }, { data: [5, null, -3] }], 3)).toEqual([
      [{ from: 0, to: 10 }, { from: 0, to: 20 }, { from: 0, to: 5 }],
      [{ from: 10, to: 15 }, null, { from: 0, to: -3 }],
    ]);
    expect(totalAt([{ data: [10, 20] }, { data: [5, null] }], 0)).toBe(15);
    expect(totalAt([{ data: [10, 20] }, { data: [5, null] }], 1)).toBe(20);
    expect(totalAt([{ data: [null] }], 0)).toBeNull();
  });
});

describe("scales", () => {
  it("pads 8%, and starts at zero only when asked", () => {
    expect(scaleFor([50, 100], true)).toEqual({ min: 0, max: 108 });
    const hugging = scaleFor([18, 20], false);
    expect(hugging.min).toBeCloseTo(17.84);
    expect(hugging.max).toBeCloseTo(20.16);
    expect(scaleFor([], true)).toEqual({ min: 0, max: 1 });
  });
  it("gives a combo's other-unit line a right scale of its own", () => {
    expect(isOnRightScale("combo", 1, "%", undefined, "₹Cr")).toBe(true);
    expect(isOnRightScale("combo", 1, undefined, "right", "₹Cr")).toBe(true);
    expect(isOnRightScale("combo", 1, undefined, undefined, "₹Cr")).toBe(false);
    expect(isOnRightScale("combo", 0, "%", "right", "₹Cr")).toBe(false);  // the bars stay left
    expect(isOnRightScale("line", 1, "%", "right", "₹Cr")).toBe(false);   // only a combo has two scales
    const spec = chart({ type: "combo", unit: "₹Cr", x: ["a", "b"], series: [{ data: [100, 200] }, { unit: "%", data: [18, 20] }] })!;
    const { left, right } = chartScales(spec, null);
    expect(left.min).toBe(0);
    expect(right!.min).toBeCloseTo(17.84);
  });
  it("writes shares with one decimal under 10%", () => {
    expect(sharePct(0.0625)).toBe("6.3%");
    expect(sharePct(0.09)).toBe("9%");
    expect(sharePct(0.4)).toBe("40%");
  });
});

describe("parseChart, the new kinds", () => {
  it("reads a pie: x are the slices, the first series their values, the others ignored", () => {
    const s = chart({ type: "pie", x: ["Rent", "Food", "Fun"], unit: "₹", series: [{ name: "Budget", data: [30000, 12000, 8000] }, { data: [1, 2, 3] }] })!;
    expect(s.type).toBe("pie");
    expect(s.x).toEqual(["Rent", "Food", "Fun"]);
    expect(s.series).toHaveLength(1);
    expect(s.series[0].data).toEqual([30000, 12000, 8000]);
  });
  it("reads a sloppy donut: 'Doughnut', thousands commas, a text value, a zero", () => {
    const s = parseChart('{"type":"Doughnut","x":["Equity","Debt","Gold","Cash"],"series":[{"data":[540,000, 220,000, "lots", 0]}]}');
    expect(s?.type).toBe("donut");
    expect(s?.x).toEqual(["Equity", "Debt"]);
    expect(s?.series[0].data).toEqual([540000, 220000]);
  });
  it("gives up on a pie with nothing positive, or broken JSON", () => {
    expect(chart({ type: "pie", x: ["Loss"], series: [{ data: [-5] }] })).toBeNull();
    expect(chart({ type: "donut", x: ["a", "b"], series: [{ data: [0, 0] }] })).toBeNull();
    expect(parseChart('{"type":"pie","x":["a","b"],"series":[{"data":[1,')).toBeNull();
  });
  it("lets stacked bars and areas have six parts, the rest three", () => {
    const six = Array.from({ length: 7 }, (_, k) => ({ name: `p${k}`, data: [k + 1] }));
    expect(chart({ type: "stacked", x: ["Jul"], series: six })!.series).toHaveLength(6);
    expect(chart({ type: "area", x: ["Jul"], series: six })!.series).toHaveLength(6);
    expect(chart({ type: "hbar", x: ["Jul"], series: six })!.series).toHaveLength(3);
  });
  it("reads a combo's line unit as its own, on the right", () => {
    const s = chart({ type: "combo", unit: "₹Cr", x: ["Q1", "Q2"], series: [{ name: "Revenue", data: [65799, 67087] }, { name: "Margin", unit: "%", data: [18.4, 16] }] })!;
    expect(s.series.map((x) => x.right)).toEqual([false, true]);
    expect(s.series[1].unit).toBe("%");
  });
  it("reads an hbar with a gap and a negative", () => {
    const s = chart({ type: "hbar", x: ["IT", "Bank", "Realty"], series: [{ data: [18.4, null, -7.8] }] })!;
    expect(s.type).toBe("hbar");
    expect(s.series[0].data).toEqual([18.4, null, -7.8]);
  });
  it("reads a whole chart block written into a chart fence by its kind (DeepSeek V4.1)", () => {
    const s = parseChart('{"type": "chart", "kind": "hbar", "title": "Nifty sectors · 1-year return", "x": ["Nifty Pharma", "Nifty IT"], "series": [{"name": "1y return", "data": [17.4, -20.4]}], "unit": "%"}');
    expect(s?.type).toBe("hbar");
    expect(chart({ type: "chart", x: ["a"], series: [{ data: [1] }] })?.type).toBe("line");
  });
  it("takes the kind from a chart block in a fence", () => {
    for (const kind of ["pie", "donut", "stacked", "hbar", "area", "combo"]) {
      const out = readBlocks(JSON.stringify([{ type: "chart", kind, x: ["a", "b"], series: [{ name: "s", data: [1, 2] }] }]))!;
      expect(out.dropped, kind).toEqual([]);
      const block = out.blocks[0];
      expect(block.type === "chart" && block.spec.type, kind).toBe(kind);
    }
    const unknown = readBlocks(JSON.stringify([{ type: "chart", kind: "radar", x: ["a"], series: [{ data: [1] }] }]))!.blocks[0];
    expect(unknown.type === "chart" && unknown.spec.type).toBe("line");
  });
});

describe("drawing the new kinds", () => {
  it("draws a pie as one wedge a slice, with each share and value in a legend under it", () => {
    const html = draw(chart({ type: "pie", title: "Budget", unit: "₹", x: ["Rent", "Food", "Fun"], series: [{ data: [30000, 15000, 5000] }] })!);
    expect(count(html, "path")).toBe(3);
    expect(count(html, "tr")).toBe(3);
    expect(html).toContain("60%");
    expect(html).toContain("₹30,000");
    expect(html).toContain("₹50,000");  // the total, above the pie
    expect(html).toContain("Total");
  });
  it("draws a single-slice pie as a whole circle", () => {
    const html = draw(chart({ type: "pie", x: ["All"], series: [{ data: [10] }] })!);
    expect(html).toMatch(/A96,96 0 1 1/);
    expect(html).toContain("100%");
  });
  it("draws a donut with the total in its hole, and an Other slice in grey", () => {
    const x = ["a", "b", "c", "d", "e", "f", "g", "h", "i"];
    const html = draw(chart({ type: "donut", unit: "₹", x, series: [{ data: [20, 15, 14, 12, 10, 9, 8, 7, 5] }] })!);
    expect(count(html, "path")).toBe(8);
    expect(html).toContain("Other");
    expect(html).toContain("var(--t-dim)");
    expect(html).toMatch(/<text[^>]*>₹100<\/text>/);  // 20 + 15 + … + 5 = 100, in the middle
  });
  it("draws shares given in % without repeating them: the biggest slice in the middle, no value column", () => {
    const html = draw(chart({ type: "donut", unit: "%", x: ["Equity", "Debt", "Gold"], series: [{ data: [60, 30, 10] }] })!);
    expect(html).toMatch(/<text[^>]*>60%<\/text>/);
    expect(html).toMatch(/<text[^>]*>Equity<\/text>/);
    expect(count(html, "td")).toBe(9);  // dot, name and share for each of the 3 slices
  });
  it("draws stacked bars, a part per series per label, and the total as the big number", () => {
    const html = draw(chart({ type: "stacked", unit: "₹", x: ["Jul", "Aug"], series: [{ name: "Rent", data: [30000, 30000] }, { name: "Food", data: [14000, 15500] }] })!);
    expect(count(html, "rect")).toBe(4);
    expect(html).toContain("₹45,500");  // Aug's total
    const withZero = draw(chart({ type: "stacked", x: ["Jul"], series: [{ data: [3] }, { data: [0] }] })!);
    expect(count(withZero, "rect")).toBe(1);  // a zero part isn't drawn as a sliver
    expect(html).toContain("var(--t-chart-2)");
    expect(html).toMatch(/Rent<span[^>]*>₹30,000/);  // each part's value in the legend
  });
  it("draws horizontal bars with the names as text, so long ones wrap, and a negative to the left of zero", () => {
    const html = draw(chart({ type: "hbar", unit: "%", x: ["Nifty Information Technology", "Nifty Realty"], series: [{ data: [18, -6] }] })!);
    expect(html).toContain("Nifty Information Technology");
    expect(html).toContain("18%");
    expect(html).toContain("-6%");
    expect(html).toContain("left:25%");  // zero sits a quarter in (-6 to 18), so the 18 bar starts there
  });
  it("draws areas piled up, a filled band and an edge per series", () => {
    const html = draw(chart({ type: "area", unit: "₹", x: ["Start", "Yr 3", "Yr 6"], series: [{ name: "Invested", data: [0, 360000, 720000] }, { name: "Gains", data: [0, 75076, 337570] }] })!);
    expect(count(html, "path")).toBe(4);
    expect(html).toContain("₹10.58L");  // invested + gains at Yr 6
    expect(html).toContain("Gains");
  });
  it("draws a combo as bars and a dotted line, saying which series has the right scale", () => {
    const html = draw(chart({ type: "combo", unit: "₹Cr", x: ["Q1", "Q2", "Q3"], series: [{ name: "Revenue", data: [65799, 67087, 70698] }, { name: "Margin", unit: "%", data: [18.4, 16, 19.5] }] })!);
    expect(count(html, "rect")).toBe(3);
    expect(count(html, "circle")).toBe(3);
    expect(html).toContain("(right scale)");
    expect(html).toContain("Margin 19.5%");  // the line's value beside the bars', in its own unit
  });
  it("still draws a line and a bar chart as before", () => {
    const line = draw(chart({ type: "line", x: ["a", "b"], series: [{ data: [1, 2] }] })!);
    expect(line).toContain("chart-draw");
    expect(line).not.toContain("--t-chart-");
    const bar = draw(chart({ type: "bar", x: ["a", "b"], series: [{ data: [1, 2] }] })!);
    expect(count(bar, "rect")).toBe(2);
    expect(bar).not.toContain("--t-chart-");
  });
});
