import { describe, expect, it } from "vitest";
import { changePct, parseChart, smoothPath } from "./ChartBlock";
import { fmt } from "./chartData";
import { drawWidth } from "./chartWidth";

describe("parseChart", () => {
  it("accepts the market tool's block", () => {
    const s = parseChart('{"type":"line","title":"NIFTY 50 · 5d","x":["24 Sep","25 Sep"],"series":[{"name":"Close","data":[23063.1,22421.9]}],"unit":"INR"}')!;
    expect(s.type).toBe("line"); expect(s.series[0].data).toEqual([23063.1, 22421.9]);
  });
  it("rejects partial or unrelated JSON", () => {
    expect(parseChart('{"type":"line","x":["a"')).toBeNull();
    expect(parseChart('{"name":"not a chart"}')).toBeNull();
    expect(parseChart('{"x":["a"],"series":[{"data":["oops"]}]}')).toBeNull();
  });
  it("defaults unknown types to line and keeps at most three series", () => {
    const s = parseChart('{"type":"scatter","x":["a","b"],"series":[{"data":[1,2]},{"data":[1,2]},{"data":[1,2]},{"data":[1,2]}]}')!;
    expect(s.type).toBe("line"); expect(s.series.length).toBe(3);
  });
});

describe("changePct", () => {
  it("is first to last, skipping nulls", () => {
    expect(changePct([null, 100, 105, null, 110])).toBeCloseTo(10);
    expect(changePct([5])).toBeNull();
    expect(changePct([0, 3])).toBeNull();
  });
});

describe("smoothPath", () => {
  it("starts at the first point and ends at the last", () => {
    const d = smoothPath([[0, 10], [10, 0], [20, 10]]);
    expect(d.startsWith("M0,10")).toBe(true);
    expect(d.endsWith("20,10")).toBe(true);
  });
});

describe("fmt", () => {
  it("keeps US millions and percentages in plain grouping, lakhs only for rupees", () => {
    expect(fmt(109417, "$M")).toBe("$109,417M");
    expect(fmt(34.0, "%")).toBe("34%");
    expect(fmt(250000, "₹")).toBe("₹2.50L");
    expect(fmt(294059, "₹Cr")).toBe("₹2,94,059 Cr");
  });
});

describe("drawWidth", () => {
  it("draws 320 wide on a phone, scaled to fit as always", () => {
    expect(drawWidth(0)).toBe(320);
    expect(drawWidth(300)).toBe(320);
    expect(drawWidth(480)).toBe(320);
  });
  it("draws a wide chart at its own width (1.3x), so it spreads sideways instead of growing tall", () => {
    expect(drawWidth(740)).toBe(569);
    expect(drawWidth(650)).toBe(500);
  });
});
