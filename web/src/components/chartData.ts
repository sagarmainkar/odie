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
  /** false: no headline number or change chip (a % change comparison, where a change of a change means nothing). */
  figure?: boolean;
  /** "change": a one-series line is green above its first value and orange below it, with the start marked. */
  tone?: "change";
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

/** From this size up, numbers are shortened (4.21B, 18.4L); hover cards and title attributes show them in full. */
export const SHORT_FROM = 100_000;

// Longest unit written after a number ("participants"); a longer one is a phrase the title should carry.
const MAX_UNIT = 12;

/** A big number shortened the way the reader says it, to 3 significant digits (Intl's compact notation).
 *  en-US: 4213500000 → "4.21B";  en-GB → "4.21bn";  de-DE → "4,21 Mrd.";  ja-JP → "42.1億";  en-IN: 1840000 → "18.4L" */
export function formatCompact(v: number, locale: string = userLocale()): string {
  return new Intl.NumberFormat(locale, { notation: "compact", maximumSignificantDigits: 3 }).format(v);
}

/**
 * Which locale shortens an amount. Rupees always read in lakh and crore, and so do plain numbers on an Indian install;
 * any other amount (dollars, kilograms) in the reader's own words, but never in lakh and crore, which are for rupees.
 *   ("₹", en-US) → "en-IN";  (no unit, en-IN) → "en-IN";  ("$", en-IN) → "en";  ("$", de-DE) → "de-DE"
 */
function compactLocale(rupees: boolean, unit: string | undefined): string {
  if (rupees) return "en-IN";
  if (!unit && usesLakhCrore()) return "en-IN";
  if (usesLakhCrore()) return "en";
  return userLocale();
}

// A unit that is a currency sign on its own: it goes in front of the number ("$4.21B").
const CURRENCY_SIGN = /^[$€£¥]$/;

/** A big number shortened for its unit, the unit itself left out. The words follow compactLocale, so dollars and
 *  other units never read in lakh and crore. en-IN: (1840000, "USD") → "1.84M";  (1840000) → "18.4L";  (-250000, "$") → "-250K" */
export function shortNumber(v: number, unit?: string): string {
  const rupees = unit === "₹" || unit === "INR";
  return `${v < 0 ? "-" : ""}${formatCompact(Math.abs(v), compactLocale(rupees, unit))}`;
}

/**
 * A value with its unit, as charts, tables and cards show it. Big numbers (100,000 and up) are shortened unless `full`
 * is set (hover cards and title attributes), which keeps every digit and up to 2 decimals. Money already in a scale
 * ("$M", "₹Cr") is never shortened again. A word unit goes after a space; "pts" and anything longer than 12 characters
 * are left out.
 *   en-US: 4213500000 → "4.21B" (full: "4,213,500,000");  (23063.1, full) → "23,063.1";  (1840000, "₹") → "₹18.4L";
 *   (4213500000, "$") → "$4.21B";
 *   (18.6, "%") → "18.6%";  (109417, "$M") → "$109,417M";  (1500000, "kg") → "1.5M kg";  (12, "people") → "12 people"
 *   en-IN: 2500000 → "25L";  de-DE: 4213500000 → "4,21 Mrd."
 */
export function fmt(v: number, unit?: string, { full = false }: { full?: boolean } = {}): string {
  if (unit && /^\D(Cr|K|M|B)$/.test(unit)) return formatAmount(v, unit) ?? String(v);
  if (unit === "%") return `${v.toLocaleString(userLocale(), { maximumFractionDigits: 1 })}%`;
  const abs = Math.abs(v);
  const rupees = unit === "₹" || unit === "INR";
  let sign = "";
  if (rupees) sign = "₹";
  else if (unit && CURRENCY_SIGN.test(unit)) sign = unit;
  let digits: string;
  if (!full && abs >= SHORT_FROM) {
    digits = formatCompact(abs, compactLocale(rupees, unit));
  } else {
    const locale = rupees ? "en-IN" : userLocale();
    const decimals = full || abs < 1000 ? 2 : 0;  // a shown price keeps its paise; a chart axis rounds from 1,000 up
    digits = abs.toLocaleString(locale, { maximumFractionDigits: decimals });
  }
  const signed = `${v < 0 ? "-" : ""}${sign}${digits}`;
  const unitLeftOut = sign !== "" || !unit || unit === "pts" || unit.length > MAX_UNIT;
  if (unitLeftOut) return signed;
  return `${signed} ${unit}`;
}

/** First to last value as a percentage (gaps skipped); null when there's nothing to compare. [100, null, 110] → 10 */
export function changePct(data: (number | null)[]): number | null {
  const v = data.filter((x): x is number => x !== null);
  if (v.length < 2 || v[0] === 0) return null;
  return ((v[v.length - 1] - v[0]) / Math.abs(v[0])) * 100;
}

/** A series's name for the legend, the hover card and line ends; an only series without one is just "Value".
 *  [{name: "Close"}] at 0 → "Close";  [{}] at 0 → "Value";  [{}, {}] at 1 → "Series 2" */
export function seriesName(series: { name?: string }[], k: number): string {
  const name = series[k].name;
  if (name) return name;
  if (series.length === 1) return "Value";
  return `Series ${k + 1}`;
}

/** A pie slice's share of the total as a hover note, among values that are all zero or more:
 *  (40, [40, 60]) → "40% of total"; undefined when any value is negative or they add up to nothing. */
export function shareNote(values: (number | null)[], v: number): string | undefined {
  const known = values.filter((d): d is number => d !== null);
  const total = known.reduce((sum, d) => sum + d, 0);
  if (known.some((d) => d < 0) || total <= 0) return undefined;
  return `${sharePct(v / total)} of total`;
}

// Labels with a natural order. Months (with a year or day), quarters (with a year or FY), financial years, dates and
// steps like "Year 3"; plain numbers (a year, or a calculator's 0, 0.25, 0.5 …) too.
const MONTH = "(jan(uary)?|feb(ruary)?|mar(ch)?|apr(il)?|may|june?|july?|aug(ust)?|sep(t(ember)?)?|oct(ober)?|nov(ember)?|dec(ember)?)\\.?";
const YEAR = "('?\\d{2}|\\d{4})";
const FY = `(fy\\s*)?${YEAR}([-/]\\d{2,4})?`;  // 25, 2025, FY25, FY2024-25
const ORDERED = [
  `-?\\d+(\\.\\d+)?`,                                   // 2024, 7, 0.25
  `${MONTH}(\\s*[-'’/]?\\s*${YEAR})?`,                // Jan, March 2025, Jan '25, Jan-25
  `\\d{1,2}\\s+${MONTH}(,?\\s+${YEAR})?`,             // 12 Oct, 12 Oct 2025
  `${MONTH}\\s+\\d{1,2}(,?\\s+\\d{4})?`,              // Oct 12, Oct 12, 2025
  `q[1-4](\\s*[-'’]?\\s*${FY})?`,                     // Q1, Q3 2025, Q1 FY25, Q4'24
  `${FY}\\s*-?\\s*q[1-4]`,                            // 2025 Q1, FY25 Q2
  `fy\\s*${YEAR}([-/]\\d{2,4})?`,                     // FY24, FY2024-25, FY 24-25
  `\\d{4}-\\d{2}(-\\d{2}([t ].*)?)?`,                 // 2025-11, 2025-11-03, 2025-11-03T09:15
  `\\d{1,2}[/.-]\\d{1,2}[/.-]\\d{2,4}`,               // 03/11/2025, 3.11.25
  `(year|yr|month|week|wk|day|hour|hr)s?\\s*\\d+`,    // Year 3, Week 12
].map((p) => new RegExp(`^${p}$`, "i"));

/** Whether a label has a natural order, so its bars must stay columns read left to right.
 *  "Q3 FY2024-25" → true;  "12 Oct" → true;  "2024" → true;  "Rent" → false;  "Octopus" → false */
export function isOrderedLabel(label: string | number): boolean {
  const text = String(label).trim();
  return ORDERED.some((re) => re.test(text));
}

// Bars lie down when a label is longer than this, and when one series ranks this many or more.
const LONG_LABEL = 12;
const LONG_RANKING = 9;

/**
 * The kind a chart is drawn as: a bar chart lies down (hbar) when the model asked for horizontal bars, or its labels
 * read better as rows, unless they have a natural order (months, quarters, years, dates), which always stay columns.
 * Rows when any label is longer than 12 characters, there are only 2 or 3 items, or a single series ranks 9 or more.
 * Every other kind is drawn as asked.
 *   bar of ["Stay", "Flights", "Local transport"] → hbar;  bar of ["Q1", "Q2"] → bar;  bar of 10 cities, one series →
 *   hbar;  bar of 4 short names, two series → bar;  hbar of ["Q1", "Q2"] → hbar (asked for)
 */
export function kindToDraw(spec: ChartSpec): ChartKind {
  if (spec.type !== "bar") return spec.type;
  const { x } = spec;
  if (x.every(isOrderedLabel)) return "bar";
  const longLabel = x.some((label) => String(label).length > LONG_LABEL);
  const fewItems = x.length >= 2 && x.length <= 3;
  const longRanking = spec.series.length === 1 && x.length >= LONG_RANKING;
  if (longLabel || fewItems || longRanking) return "hbar";
  return "bar";
}
