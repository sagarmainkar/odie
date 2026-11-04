// How chart numbers read (fmt, in several locales) and which way bars are drawn (kindToDraw).
import { afterEach, describe, expect, it } from "vitest";
import { rememberLocale } from "../locale";
import { parseChart } from "./ChartBlock";
import { fmt, formatCompact, isOrderedLabel, kindToDraw, seriesName, shareNote, type ChartKind, type ChartSpec } from "./chartData";

afterEach(() => rememberLocale("en-IN"));

describe("numbers from 100,000 up are shortened in the reader's own words", () => {
  it("in the US", () => {
    rememberLocale("en-US");
    expect(fmt(4213500000)).toBe("4.21B");
    expect(fmt(4213500000, undefined, { full: true })).toBe("4,213,500,000");
    expect(fmt(4213500000, "$")).toBe("$4.21B");
    expect(fmt(1500000, "kg")).toBe("1.5M kg");
    expect(fmt(99999)).toBe("99,999");  // under 100,000: every digit
    expect(fmt(-250000, "$")).toBe("-$250K");
  });
  it("in Germany and Japan", () => {
    rememberLocale("de-DE");
    expect(fmt(4213500000)).toBe("4,21\u00a0Mrd.");  // Intl puts a no-break space before Mrd.
    expect(fmt(18.6, "%")).toBe("18,6%");
    expect(formatCompact(4213500000, "ja-JP")).toBe("42.1億");
  });
  it("in lakh and crore for rupees anywhere, and for plain numbers on an Indian install", () => {
    rememberLocale("en-US");
    expect(fmt(1840000, "₹")).toBe("₹18.4L");
    expect(fmt(1840000, "₹", { full: true })).toBe("₹18,40,000");
    rememberLocale("en-IN");
    expect(fmt(2500000)).toBe("25L");
    expect(fmt(4213500000, "$")).toBe("$4.21B");  // dollars never in crore
  });
  it("leaves money already in a scale alone, and writes word units after the number", () => {
    rememberLocale("en-US");
    expect(fmt(109417, "$M")).toBe("$109,417M");
    expect(fmt(294059, "₹Cr")).toBe("₹2,94,059 Cr");
    expect(fmt(12, "people")).toBe("12 people");
    expect(fmt(24310, "pts")).toBe("24,310");
    expect(fmt(5, "people in the queue today")).toBe("5");  // a phrase is the title's job
  });
});

describe("isOrderedLabel", () => {
  it("knows months, quarters, years, financial years and dates", () => {
    for (const label of ["Jan", "january", "Sept", "Mar 2025", "Jan '25", "Jan-25", "Q1", "Q3 2025", "Q1 FY25",
      "Q4'24", "Q3 FY2024-25", "2025 Q1", "FY25 Q2", "1999", "2024", "FY24", "FY2024-25", "FY 24-25",
      "2025-11-03", "2025-11", "03/11/2025", "12 Oct", "12 Oct 2025", "Oct 12", "Oct 12, 2025", "Year 3", "Week 12", "Day 1"]) {
      expect(isOrderedLabel(label), label).toBe(true);
    }
  });
  it("leaves names, categories and odd labels alone", () => {
    for (const label of ["Rent", "Mumbai", "IT", "Q5", "Marketing", "Octopus", "FY", "Stay", "A1", "Mayfair"]) {
      expect(isOrderedLabel(label), label).toBe(false);
    }
  });
});

describe("kindToDraw (columns or horizontal bars)", () => {
  const spec = (x: string[], seriesCount = 1, type: ChartKind = "bar"): ChartSpec =>
    ({ type, x, series: Array.from({ length: seriesCount }, () => ({ data: x.map((_, i) => i + 1) })) });
  const many = (n: number) => Array.from({ length: n }, (_, i) => `Item ${String.fromCharCode(65 + i)}`);

  it("keeps time-ordered labels as columns whatever else is true", () => {
    expect(kindToDraw(spec(["Q1", "Q2"]))).toBe("bar");
    expect(kindToDraw(spec(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct"]))).toBe("bar");
    expect(kindToDraw(spec(["Q1 FY2024-25", "Q2 FY2024-25", "Q3 FY2024-25", "Q4 FY2024-25"]))).toBe("bar");
  });
  it("lies down when a label is longer than 12 characters", () => {
    expect(kindToDraw(spec(["Stay", "Flights", "Food", "Local transport"]))).toBe("hbar");
    expect(kindToDraw(spec(["Stay", "Flights", "Food", "Activities"]))).toBe("bar");
  });
  it("lies down for only 2 or 3 items", () => {
    expect(kindToDraw(spec(["HDFC", "ICICI"]))).toBe("hbar");
    expect(kindToDraw(spec(["A", "B", "C"], 2))).toBe("hbar");
    expect(kindToDraw(spec(["Solo"]))).toBe("bar");
  });
  it("lies down for a single-series ranking of 9 or more", () => {
    expect(kindToDraw(spec(many(9)))).toBe("hbar");
    expect(kindToDraw(spec(many(8)))).toBe("bar");
    expect(kindToDraw(spec(many(9), 2))).toBe("bar");
  });
  it("always draws an asked-for hbar and never changes other kinds", () => {
    expect(kindToDraw(spec(["Q1", "Q2", "Q3", "Q4"], 1, "hbar"))).toBe("hbar");
    expect(kindToDraw(spec(["HDFC", "ICICI"], 1, "line"))).toBe("line");
    expect(kindToDraw(spec(many(10), 1, "stacked"))).toBe("stacked");
  });
});

describe("the optional tone and figure fields", () => {
  const line = (extra: object) => parseChart(JSON.stringify({ type: "line", x: ["a", "b"], series: [{ data: [1, 2] }], ...extra }))!;
  it("read only the exact values, and ignore the rest so older answers still draw", () => {
    expect(line({ tone: "change" }).tone).toBe("change");
    expect(line({ tone: "Change" }).tone).toBeUndefined();
    expect(line({ tone: true }).tone).toBeUndefined();
    expect(line({ figure: false }).figure).toBe(false);
    expect(line({ figure: "false" }).figure).toBeUndefined();
    expect(line({}).tone).toBeUndefined();
  });
});

describe("names and notes", () => {
  it("call an only unnamed series Value, and later ones by number", () => {
    expect(seriesName([{ name: "Close" }], 0)).toBe("Close");
    expect(seriesName([{}], 0)).toBe("Value");
    expect(seriesName([{}, {}], 1)).toBe("Series 2");
  });
  it("give a slice its share of the total, only among values that can be shares", () => {
    expect(shareNote([40, 60], 40)).toBe("40% of total");
    expect(shareNote([40, -60], 40)).toBeUndefined();
  });
});

describe("fmt in full", () => {
  it("keeps a price's decimals for hover cards and titles", () => {
    rememberLocale("en-US");
    expect(fmt(23063.1, undefined, { full: true })).toBe("23,063.1");
    expect(fmt(3082.15, "INR", { full: true })).toBe("₹3,082.15");
    expect(fmt(24310, "pts", { full: true })).toBe("24,310");
  });
});
