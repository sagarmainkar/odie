import { describe, expect, it } from "vitest";
import { parseChart } from "./ChartBlock";
import { changePct, fmt } from "./chartData";
import { smoothPath } from "./chartGeometry";

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
    expect(fmt(250000, "₹")).toBe("₹2.5L");
    expect(fmt(294059, "₹Cr")).toBe("₹2,94,059 Cr");
  });
});
