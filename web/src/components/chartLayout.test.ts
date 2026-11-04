// Where everything goes in an up-and-down chart (chartLayout.ts), and what its hover card says.
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { chartScales, type ChartSpec } from "./chartData";
import { rememberLocale } from "../locale";
import { namesFitAtEnds, startLabelY, xyLayout, xyTip } from "./chartLayout";

beforeEach(() => rememberLocale("en-US"));
afterEach(() => rememberLocale("en-IN"));

const layoutOf = (spec: ChartSpec, width = 600) => xyLayout(spec, width, chartScales(spec, null));
const months = (n: number) => ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan"].slice(0, n);
const bars = (n: number, series = 1): ChartSpec => ({ type: "bar", x: months(n),
  series: Array.from({ length: series }, (_, k) => ({ name: `S${k}`, data: months(n).map((_, i) => 100 + i + k) })) });

describe("xyLayout", () => {
  it("draws at the width it is given, columns 210px and lines 220px high", () => {
    expect(layoutOf(bars(4)).W).toBe(600);
    expect(layoutOf(bars(4)).H).toBe(210);
    expect(layoutOf({ type: "line", x: ["a", "b"], series: [{ data: [1, 2] }] }).H).toBe(220);
  });

  it("prints values on the bars only when there are 12 or fewer", () => {
    expect(layoutOf(bars(5)).valueLabels).toBe(true);
    expect(layoutOf(bars(6, 2)).valueLabels).toBe(true);
    expect(layoutOf(bars(13)).valueLabels).toBe(false);
    expect(layoutOf(bars(7, 2)).valueLabels).toBe(false);
  });

  it("drops the values when they wouldn't fit over their bars", () => {
    expect(layoutOf(bars(12), 200).valueLabels).toBe(false);
  });

  it("centres a few columns instead of spreading them out", () => {
    const l = layoutOf(bars(3));
    expect(l.xAt(1) - l.xAt(0)).toBe(96);
    expect(l.xAt(1)).toBeCloseTo(300);
  });

  it("writes as many x labels as fit 80px apart on a line", () => {
    const x = Array.from({ length: 53 }, (_, i) => `W${i}`);
    const l = layoutOf({ type: "line", x, series: [{ data: x.map((_, i) => i) }] });
    expect(l.xLabels.length).toBeGreaterThan(2);
    for (let k = 1; k < l.xLabels.length; k++) expect(l.xAt(l.xLabels[k]) - l.xAt(l.xLabels[k - 1])).toBeGreaterThanOrEqual(80);
  });

  it("ends a one-series line with its last value", () => {
    const l = layoutOf({ type: "line", x: ["a", "b", "c"], unit: "$", series: [{ data: [10, 12, null] }] });
    expect(l.ends.map((e) => e.text)).toEqual(["$12"]);
  });

  it("names each of several lines at its end, at least 14px apart", () => {
    const l = layoutOf({ type: "line", unit: "%", x: ["a", "b"], series: [{ name: "HDFC Bank", data: [0, 10] }, { name: "ICICI Bank", data: [0, 10.1] }] });
    expect(l.ends.map((e) => e.text)).toEqual(["HDFC Bank", "ICICI Bank"]);
    expect(Math.abs(l.ends[0].y - l.ends[1].y)).toBeGreaterThan(13.99);
    expect(l.ends[1].ink).toBe("var(--t-chart-2)");
  });
});

describe("gridlines", () => {
  const rebased: ChartSpec = { type: "line", unit: "%", x: ["a", "b", "c"],
    series: [{ name: "NIFTY 50", data: [0, 4.2, 18.5] }, { name: "S&P 500", data: [0, -4.2, 9] }] };

  it("give several lines round values on the left, the scale running from the lowest to the highest", () => {
    const l = layoutOf(rebased);
    expect(l.ticks).toEqual([-10, 0, 10, 20]);
    expect(l.yAt(-10)).toBeCloseTo(l.base);
    expect(l.yAt(20)).toBeCloseTo(l.top);
    expect(l.left).toBeGreaterThan(30);  // room for "-10%"
  });
  it("leave one line, and bars, without them", () => {
    expect(layoutOf({ ...rebased, series: rebased.series.slice(0, 1) }).ticks).toEqual([]);
    expect(layoutOf(bars(4, 2)).ticks).toEqual([]);
  });
});

describe("xyTip", () => {
  it("shows a bar's full value and no share (bars are not parts of a whole)", () => {
    const spec: ChartSpec = { type: "bar", x: ["Q1", "Q2"], series: [{ name: "Revenue", data: [4213500000, 6320250000] }] };
    const tip = xyTip(spec, 0, layoutOf(spec));
    expect(tip.title).toBe("Q1");
    expect(tip.rows).toEqual([{ colour: "var(--t-chart-1)", name: "Revenue", value: "4,213,500,000" }]);
    expect(tip.note).toBeUndefined();
  });

  it("gives a one-series line its change since the start", () => {
    const spec: ChartSpec = { type: "line", x: ["a", "b"], series: [{ data: [100, 104.2] }] };
    const tip = xyTip(spec, 1, layoutOf(spec));
    expect(tip.rows[0].name).toBe("Value");
    expect(tip.note).toBe("▲ 4.2% since start");
    expect(xyTip(spec, 0, layoutOf(spec)).note).toBeUndefined();
  });

  it("lists every series with its own colour and leaves out gaps", () => {
    const spec: ChartSpec = { type: "line", x: ["a", "b"], series: [{ name: "A", data: [1, 2] }, { name: "B", data: [null, 3] }] };
    expect(xyTip(spec, 0, layoutOf(spec)).rows.map((r) => r.name)).toEqual(["A"]);
    expect(xyTip(spec, 1, layoutOf(spec)).rows.map((r) => r.colour)).toEqual(["var(--t-chart-1)", "var(--t-chart-2)"]);
  });

  it("colours a change line's row green above the start and orange below", () => {
    const spec: ChartSpec = { type: "line", tone: "change", x: ["a", "b", "c"], series: [{ data: [100, 90, 110] }] };
    expect(xyTip(spec, 1, layoutOf(spec)).rows[0].colour).toBe("var(--t-warn)");
    expect(xyTip(spec, 2, layoutOf(spec)).rows[0].colour).toBe("var(--t-good)");
  });
});

describe("startLabelY (the Start label beside a change line's dashed start)", () => {
  // The label spans x 10-80; the dashed line is at y 100; the plot's bottom is at 194.
  const place = (points: [number, number][], y = 100) => startLabelY(points, 10, 80, y, 194);

  it("goes below the dashed line when the series climbs under the label", () => {
    expect(place([[8, 100], [60, 40], [120, 30]])).toBe(114);
  });
  it("goes above when the series falls, or stays flat", () => {
    expect(place([[8, 100], [60, 160], [120, 170]])).toBe(94);
    expect(place([[8, 100], [300, 100]])).toBe(94);
  });
  it("reads the series between its points, so a sparse line still counts", () => {
    // Points at 8 and 400 only: under the label the line has already climbed a little.
    expect(place([[8, 100], [400, 20]])).toBe(114);
  });
  it("follows the bigger move when the series goes both ways under the label", () => {
    expect(place([[8, 100], [30, 90], [60, 150]])).toBe(94);
    expect(place([[8, 100], [30, 110], [60, 50]])).toBe(114);
  });
  it("stays on the drawing: below near the top, above near the bottom", () => {
    expect(place([[8, 12], [60, 80]], 12)).toBe(26);
    expect(place([[8, 190], [60, 120]], 190)).toBe(184);
  });
});

describe("names at the ends of several lines", () => {
  const two = (a: string, b: string): ChartSpec => ({ type: "line", unit: "%", x: ["a", "b"],
    series: [{ name: a, data: [0, 4] }, { name: b, data: [0, -2] }] });

  it("go at the line ends when they are short and leave the lines most of the width", () => {
    expect(namesFitAtEnds(two("TCS", "Infosys"), 560)).toBe(true);
    expect(namesFitAtEnds(two("TCS", "Infosys"), 100)).toBe(false);  // a sliver of a chart: the legend instead
  });
  it("give way to a legend when a name is long, and then the ends keep only their dots", () => {
    const spec = two("Tata Consultancy Services", "Infosys");
    expect(namesFitAtEnds(spec, 560)).toBe(false);
    expect(layoutOf(spec, 560).ends.map((e) => e.text)).toEqual(["", ""]);
  });
  it("aren't needed for one line, which ends in its value", () => {
    expect(namesFitAtEnds({ type: "line", x: ["a", "b"], series: [{ name: "Close", data: [1, 2] }] }, 560)).toBe(false);
  });
});
