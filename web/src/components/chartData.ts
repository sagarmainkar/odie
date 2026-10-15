// The sums behind the chart kinds (ChartBlock.tsx, PieChart.tsx, HBarChart.tsx): which kind a name means, pie slices,
// stacking, scales, how a value reads. Their own file so the component files export only components.
import { formatAmount } from "../blocks/parse";
import { userLocale, usesLakhCrore } from "../locale";

/** Every kind the chart block draws. line and bar are the originals; the rest came on 2026-10-12. */
export const CHART_KINDS = ["line", "bar", "area", "stacked", "hbar", "combo", "pie", "donut"] as const;
export type ChartKind = (typeof CHART_KINDS)[number];

/** One series: its values (null for a gap), and for a combo's line its own unit and whether it has the right scale. */
export type ChartSeries = { name?: string; data: (number | null)[]; unit?: string; right?: boolean };

/** A chart ready to draw (parseChart in ChartBlock.tsx makes one). */
export type ChartSpec = {
  type: ChartKind; title?: string; x: (string | number)[];
  series: ChartSeries[]; unit?: string; source?: string;
};

// Other names models use for the same kinds, written without spaces, dashes or underscores.
const KIND_ALIASES: Record<string, ChartKind> = { doughnut: "donut", stackedbar: "stacked", horizontalbar: "hbar", barh: "hbar" };

/** The kind to draw for the name the model wrote: a known name (any case) or an alias is that kind, anything else is a
 *  line. "pie" -> pie; "Donut" -> donut; "stacked_bar" -> stacked; "scatter" -> line; undefined -> line. */
export function chartKind(name: unknown): ChartKind {
  if (typeof name !== "string") return "line";
  const plain = name.toLowerCase().replace(/[\s_-]/g, "");
  const known = CHART_KINDS.find((k) => k === plain);
  if (known) return known;
  return KIND_ALIASES[plain] ?? "line";
}

/** How many series a kind draws: stacked bars and areas show up to 6 parts (a budget's categories), the rest 3. */
export function maxSeries(kind: ChartKind): number {
  if (kind === "stacked" || kind === "area") return 6;
  return 3;
}

/** Whether a combo's series is drawn against its own scale on the right: a later series (a line) whose unit differs
 *  from the chart's, or that asks for it with axis "right". The first series is the bars, always on the left.
 *  Chart unit "₹Cr": {name: "Margin", unit: "%"} -> right; {name: "Profit"} -> left; {axis: "right"} -> right;
 *  the same series in a line chart -> left (only a combo has a second scale). */
export function isOnRightScale(kind: ChartKind, index: number, seriesUnit: string | undefined, axis: unknown, chartUnit: string | undefined): boolean {
  if (kind !== "combo" || index === 0) return false;
  if (axis === "right") return true;
  return seriesUnit !== undefined && seriesUnit !== chartUnit;
}

const MAX_SLICES = 8;

/** A pie's slices from the labels and the first series: only positive values are kept (a share can't be zero or
 *  negative, and a gap has no share), and past 8 slices the 7 biggest stay, in their order, and the rest become one
 *  "Other" slice at the end.
 *  ["Rent", "Food", "Fun"], [30000, 12000, 0] -> ["Rent", "Food"], [30000, 12000];
 *  10 slices of 10, 9, 8 … 1 -> the 7 biggest (10 … 4) and "Other" 6 (3 + 2 + 1). */
export function pieSlices(x: string[], data: (number | null)[]): { x: string[]; data: number[] } {
  const slices: { label: string; value: number }[] = [];
  data.forEach((v, i) => {
    if (v !== null && v > 0 && i < x.length) slices.push({ label: x[i], value: v });
  });
  if (slices.length <= MAX_SLICES) return { x: slices.map((s) => s.label), data: slices.map((s) => s.value) };

  const biggestFirst = [...slices].sort((a, b) => b.value - a.value);
  const kept = new Set(biggestFirst.slice(0, MAX_SLICES - 1));
  const shown = slices.filter((s) => kept.has(s));
  let other = 0;
  for (const s of slices) if (!kept.has(s)) other += s.value;
  return { x: [...shown.map((s) => s.label), "Other"], data: [...shown.map((s) => s.value), other] };
}

/** One part's band in a stack: from where it starts to where it ends. */
export type Band = { from: number; to: number };

/** Stacks the series at each x label, first series at the bottom: positive values pile up from zero, negative ones
 *  down from zero, and a gap (null) adds nothing and has no band.
 *  [{data: [10, 20]}, {data: [5, null]}] -> [[{0, 10}, {0, 20}], [{10, 15}, null]]. */
export function stackSeries(series: { data: (number | null)[] }[], n: number): (Band | null)[][] {
  const up = new Array(n).fill(0);
  const down = new Array(n).fill(0);
  return series.map((s) => {
    const bands: (Band | null)[] = [];
    for (let i = 0; i < n; i++) {
      const v = s.data[i] ?? null;
      if (v === null) {
        bands.push(null);
      } else if (v >= 0) {
        bands.push({ from: up[i], to: up[i] + v });
        up[i] += v;
      } else {
        bands.push({ from: down[i], to: down[i] + v });
        down[i] += v;
      }
    }
    return bands;
  });
}

/** The sum of the series' values at one x label, gaps skipped; null when every series has a gap there.
 *  [{data: [10, 20]}, {data: [5, null]}] at 0 -> 15; at 1 -> 20. */
export function totalAt(series: { data: (number | null)[] }[], i: number): number | null {
  let total: number | null = null;
  for (const s of series) {
    const v = s.data[i] ?? null;
    if (v !== null) total = (total ?? 0) + v;
  }
  return total;
}

/** The range a scale shows for these values, padded 8% so nothing touches the edge. fromZero keeps zero in view and
 *  starts the scale there (bars, stacks and areas grow from zero); otherwise it hugs the values (a price line).
 *  [65799, 72275] fromZero -> 0 to about 78000; [18.2, 19.6] -> about 18.1 to 19.7; [] -> 0 to 1. */
export function scaleFor(values: number[], fromZero: boolean): { min: number; max: number } {
  if (!values.length) return { min: 0, max: 1 };
  let lo = Math.min(...values);
  const hi = Math.max(...values);
  if (fromZero) lo = Math.min(0, lo);
  const pad = (hi - lo || Math.abs(hi) || 1) * 0.08;
  const startsAtZero = fromZero && lo >= 0;
  return { min: startsAtZero ? 0 : lo - pad, max: hi + pad };
}

/** The colour of the kth series (or slice) in the new kinds: the chart palette in a fixed order, so a part keeps its
 *  colour whatever else is shown. A ninth would be a repeat; pies stop at 8 and the rest stop at 6. */
export function partColour(k: number): string {
  return `var(--t-chart-${(k % 8) + 1})`;
}

/** A share of a whole as a percentage for a legend: one decimal under 10% (none when it's .0), whole numbers above.
 *  0.0625 -> "6.3%"; 0.09 -> "9%"; 0.4 -> "40%"; 0.004 -> "0.4%". */
export function sharePct(share: number): string {
  const pct = share * 100;
  if (pct < 10) return `${+pct.toFixed(1)}%`;
  return `${Math.round(pct)}%`;
}

type Scale = { min: number; max: number };

/** The scales an up-and-down chart (not a pie or hbar) is drawn against. Stacked bars and areas: one, from zero to the
 *  tallest pile. Otherwise the left one fits every series without the right scale (from zero for bars and a combo's
 *  bars) and the right one, only in a combo, fits the series that have it.
 *  Combo of revenue (₹Cr, 65799-72275) and margin (%, 18.2-19.6) -> left 0 to ~78000, right ~18.1 to ~19.7;
 *  a line chart -> left fits the values, right null. */
export function chartScales(spec: ChartSpec, bands: (Band | null)[][] | null): { left: Scale; right: Scale | null } {
  if (bands) {
    const ends = bands.flat().flatMap((b) => (b === null ? [] : [b.from, b.to]));
    return { left: scaleFor(ends, true), right: null };
  }
  const leftValues = spec.series.filter((s) => !s.right).flatMap((s) => numbersOf(s.data));
  const rightValues = spec.series.filter((s) => s.right).flatMap((s) => numbersOf(s.data));
  const fromZero = spec.type === "bar" || spec.type === "combo";
  const right = rightValues.length ? scaleFor(rightValues, false) : null;
  return { left: scaleFor(leftValues, fromZero), right };
}

function numbersOf(data: (number | null)[]): number[] {
  return data.filter((v): v is number => v !== null);
}

/** A value for display: lakh/crore for rupees, and for plain numbers on an Indian install; elsewhere plain grouping. */
export function fmt(v: number, unit?: string) {
  if (unit && /^\D(Cr|K|M|B)$/.test(unit)) return formatAmount(v, unit) ?? String(v);
  if (unit === "%") return `${v.toLocaleString("en-US", { maximumFractionDigits: 1 })}%`;
  const abs = Math.abs(v);
  const rupees = unit === "₹" || unit === "INR";
  const lakhCrore = rupees || (!unit && usesLakhCrore());
  const s = lakhCrore && abs >= 1e7 ? `${(v / 1e7).toFixed(2)}Cr` : lakhCrore && abs >= 1e5 ? `${(v / 1e5).toFixed(2)}L`
    : v.toLocaleString(rupees ? "en-IN" : userLocale(), { maximumFractionDigits: abs >= 1000 ? 0 : 2 });
  return rupees ? `₹${s}` : unit && unit.length <= 3 && unit !== "pts" ? `${s} ${unit}` : s;
}
