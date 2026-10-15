import { parseChart, type ChartSpec } from "../../components/ChartBlock";
import type { Trail } from "./fields";

export type ChartBlock = { type: "chart"; spec: ChartSpec };

/**
 * chart: the chart component's own parser does the work, with the block's `kind` as the chart's type: line, bar,
 * area, stacked, hbar, combo, pie or donut; any other kind, or none, draws a line (parseChart has each one's shape).
 *   {type: "chart", kind: "bar", x: ["Q1", "Q2"], series: [{name: "Rev", data: [1, 2]}]}
 *   → {type: "chart", spec: {type: "bar", x: ["Q1", "Q2"], series: [...]}}
 *   {type: "chart", kind: "pie", x: ["Rent", "Food"], series: [{data: [30000, 12000]}]} → a pie of two slices
 * Dropped: no x labels or no series, or a pie or donut with no positive value.
 */
export function readChart(raw: any, here: Trail): ChartBlock | null {
  const spec = parseChart(JSON.stringify({ ...raw, type: raw.kind }));
  if (!spec) return here.drop("chart needs x labels and at least one series");
  return { type: "chart", spec };
}
