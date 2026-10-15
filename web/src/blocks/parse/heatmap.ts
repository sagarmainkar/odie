import { clean, keepFirst, num, str, textOrNumber, type Trail } from "./fields";

export type HeatScale = "diverging" | "sequential";
export type HeatmapBlock = {
  type: "heatmap";
  title?: string;
  rows: string[];
  cols: string[];
  values: (number | null)[][];  // one list per row, one cell per col; null where the model gave no number
  unit?: string;
  scale: HeatScale;
};

const MAX_SIDE = 12;

/**
 * heatmap: row labels, column labels and a number for each cell. A row with fewer values than there are columns is
 * dropped (a longer one is cut); extra row labels or extra value rows are left out. The scale is what the model asks
 * for, else diverging when any value is negative and sequential otherwise.
 *   {type: "heatmap", rows: ["JPM", "GS"], cols: ["Q1", "Q2"], values: [[4.1, -1.2], [7.5, 2.2]], unit: "%"}
 *   → the same, with scale "diverging" (there is a negative)
 *   {type: "heatmap", rows: ["Mon", "Tue"], cols: ["am", "pm"], values: [[3, 5], [2]]}
 *   → rows ["Mon"], values [[3, 5]], scale "sequential" (Tue's row is short, so it's dropped)
 * Dropped: the whole block when it has no rows, no cols or no usable value row.
 */
export function readHeatmap(raw: any, here: Trail): HeatmapBlock | null {
  const cols = labels(raw.cols);
  const rowLabels = labels(raw.rows);
  const rawValues = Array.isArray(raw.values) ? raw.values : [];
  if (cols.length === 0 || rowLabels.length === 0 || rawValues.length === 0) return here.drop("heatmap needs rows, cols and values");

  const keptCols = keepFirst(cols, MAX_SIDE, here, "cols");
  const rows: string[] = [];
  const values: (number | null)[][] = [];
  rowLabels.forEach((label, i) => {
    const cells = rawValues[i];
    if (!Array.isArray(cells)) {
      here.at("values").at(i).drop(`no values for row "${label}"`);
      return;
    }
    if (cells.length < keptCols.length) {
      here.at("values").at(i).drop(`row "${label}" has ${cells.length} values, the heatmap has ${keptCols.length} columns`);
      return;
    }
    rows.push(label);
    values.push(keptCols.map((_, j) => num(cells[j])));
  });
  if (rows.length === 0) return here.drop("heatmap has no usable row");

  const keptRows = keepFirst(rows, MAX_SIDE, here, "rows");
  const keptValues = values.slice(0, keptRows.length);
  return clean({
    type: "heatmap" as const,
    title: str(raw.title, 80),
    rows: keptRows,
    cols: keptCols,
    values: keptValues,
    unit: str(raw.unit, 12),
    scale: scaleOf(raw.scale, keptValues),
  });
}

/** The labels of one side as short text: ["Q1", 2026, "", null] → ["Q1", "2026"]. */
function labels(v: unknown): string[] {
  if (!Array.isArray(v)) return [];
  const out: string[] = [];
  for (const item of v) {
    const text = textOrNumber(item, 24);
    if (text !== undefined) out.push(text);
  }
  return out;
}

/**
 * Which way the cells are shaded: the model's choice when it's one of the two, else diverging when any value is
 * below zero (gains and losses), sequential otherwise (counts, hours).
 *   ("sequential", [[-1, 2]]) → "sequential";  (undefined, [[-1, 2]]) → "diverging";  (undefined, [[1, 2]]) → "sequential"
 */
export function scaleOf(asked: unknown, values: (number | null)[][]): HeatScale {
  if (asked === "sequential" || asked === "diverging") return asked;
  const anyNegative = values.some((row) => row.some((v) => v !== null && v < 0));
  return anyNegative ? "diverging" : "sequential";
}
