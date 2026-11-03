// Headline numbers (Kpis.tsx): how the big number reads, the optional trend line, and its colours.
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it } from "vitest";
import { rememberLocale } from "../locale";
import { Blocks } from "./Blocks";
import { kpiValue, sparkPath } from "./kpiValue";
import { readBlocks, type KpiItem } from "./parse";

afterEach(() => rememberLocale("en-IN"));

const draw = (json: unknown) => renderToStaticMarkup(<Blocks blocks={readBlocks(JSON.stringify(json))!.blocks} />);
const kpi = (item: Partial<KpiItem>): KpiItem => ({ label: "x", value: null, ...item });

describe("kpiValue", () => {
  it("shortens big numbers in the reader's words and keeps every digit for the title", () => {
    rememberLocale("en-US");
    expect(kpiValue(kpi({ value: 4213500000, unit: "$" }))).toBe("$4.21B");
    expect(kpiValue(kpi({ value: 4213500000, unit: "$" }), { full: true })).toBe("$4,213,500,000");
    expect(kpiValue(kpi({ value: 1840000 }))).toBe("1.84M");
    expect(kpiValue(kpi({ value: 250000, unit: "pts" }))).toBe("250K pts");
    rememberLocale("en-IN");
    expect(kpiValue(kpi({ value: 1840000 }))).toBe("18.4L");
    expect(kpiValue(kpi({ value: 1840000, unit: "₹" }))).toBe("₹18.4L");
  });
  it("leaves smaller numbers, money in a scale, years and text as they read", () => {
    rememberLocale("en-US");
    expect(kpiValue(kpi({ value: 84210 }))).toBe("84,210");
    expect(kpiValue(kpi({ value: 72275, unit: "₹Cr" }))).toBe("₹72,275 Cr");
    expect(kpiValue(kpi({ value: 18.6, unit: "%" }))).toBe("18.6%");
    expect(kpiValue(kpi({ value: 9, unit: "/10" }))).toBe("9/10");
    expect(kpiValue(kpi({ value: 1986 }))).toBe("1986");
    expect(kpiValue(kpi({ value: "Leeds United (H)" }))).toBe("Leeds United (H)");
  });
});

describe("a trend", () => {
  it("keeps its finite numbers, the last 60, and is left out (not the card) when it can't be a line", () => {
    const items = (trend: unknown) => {
      const block = readBlocks(JSON.stringify([{ type: "kpis", items: [{ label: "TCS", value: 3082, trend }] }]))!.blocks[0];
      return block.type === "kpis" ? block.items[0] : null;
    };
    expect(items([100, "90", null, 85, 80])?.trend).toEqual([100, 85, 80]);
    expect(items([5, "6"])?.trend).toBeUndefined();
    expect(items("1,2,3")?.trend).toBeUndefined();
    expect(items(Array.from({ length: 70 }, (_, i) => i))?.trend).toHaveLength(60);
    expect(items(undefined)).toEqual({ label: "TCS", value: 3082, change: null, change_unit: "%" });
  });
  it("draws as a line across the box, highest at the top", () => {
    expect(sparkPath([0, 10])).toBe("M0 26L120 2");
    expect(sparkPath([0, 10, 5])).toBe("M0 26L60 2L120 14");
    expect(sparkPath([5, 5])).toBe("M0 14L120 14");
  });
  it("takes its card's place colour when several cards have one, else the first colour", () => {
    const several = draw([{ type: "kpis", items: [{ label: "A", value: 1, trend: [1, 2] }, { label: "B", value: 2, trend: [2, 1] }] }]);
    expect(several).toContain("stroke:var(--t-chart-1)");
    expect(several).toContain("stroke:var(--t-chart-2)");
    const one = draw([{ type: "kpis", items: [{ label: "A", value: 1 }, { label: "B", value: 2, trend: [2, 1] }] }]);
    expect(one).toContain("stroke:var(--t-chart-1)");
    expect(one).not.toContain("--t-chart-2");
  });
  it("shows the full number in the card's title when it was shortened", () => {
    rememberLocale("en-US");
    const html = draw([{ type: "stat", label: "Revenue", value: 4213500000, unit: "$" }]);
    expect(html).toContain('title="$4,213,500,000"');
    expect(html).toContain(">$4.21B<");
  });
});
