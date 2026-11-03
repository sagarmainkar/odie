// How a headline number reads in a kpis or stat card (Kpis.tsx), and the path of its trend line. Their own file so
// the component file exports only components.
import { fmt, SHORT_FROM } from "../components/chartData";
import { userLocale } from "../locale";
import { formatAmount, type KpiItem } from "./parse";

/** A whole number from 1800 to 2100 with no unit reads as a year, so it gets no thousands separator.
 *  {value: 1986} → true;  {value: 1986, unit: "₹"} → false;  {value: 1986.5} → false;  {value: 2500} → false */
function isYear(k: KpiItem): boolean {
  if (typeof k.value !== "number" || k.unit) return false;
  return Number.isInteger(k.value) && k.value >= 1800 && k.value <= 2100;
}

// A unit that is a currency sign on its own: its big amounts shorten with the sign in front ("$4.21B", "₹18.4L").
const CURRENCY = /^[$₹€£¥]$/;

/**
 * A kpi value as it reads: money units through formatAmount, % stuck to the number, other units after it. The number
 * is in the user's locale (rupees stay Indian), shortened from 100,000 up unless `full` is asked for (the title).
 *   {value: 72275, unit: "₹Cr"} → "₹72,275 Cr";  {value: 18.6, unit: "%"} → "18.6%";  {value: 9, unit: "/10"} → "9/10"
 *   {value: 4213500000, unit: "$"} → "$4.21B" (full: "$4,213,500,000");  {value: 1840000} → "1.84M" (en-IN "18.4L")
 *   {value: 250000, unit: "pts"} → "250K pts";  {value: 1986} → "1986";  {value: "Leeds United (H)"} → as written
 */
export function kpiValue(k: KpiItem, { full = false }: { full?: boolean } = {}): string {
  if (k.value === null) return "–";
  if (typeof k.value === "string") return k.value;
  if (isYear(k)) return String(k.value);
  const short = !full && Math.abs(k.value) >= SHORT_FROM;
  const isCurrency = k.unit !== undefined && CURRENCY.test(k.unit);
  if (short && isCurrency) return fmt(k.value, k.unit);
  const money = formatAmount(k.value, k.unit);
  if (money !== null) return money;
  let plain: string;
  if (short) {
    plain = fmt(k.value);
  } else {
    const digits = Math.abs(k.value) >= 1000 ? 0 : 1;
    plain = k.value.toLocaleString(userLocale(), { maximumFractionDigits: digits });
  }
  if (!k.unit) return plain;
  const attached = k.unit === "%" || k.unit.startsWith("/");  // "18.6%", "9/10"; other units after a space
  if (attached) return `${plain}${k.unit}`;
  return `${plain} ${k.unit}`;
}

// The trend line's drawing box; the svg stretches it to the card's width (the stroke keeps its thickness).
export const SPARK_W = 120;
export const SPARK_H = 28;
const SPARK_PAD = 2;

/**
 * A trend's line across the box, the highest value at the top and the lowest at the bottom (2px in from each edge);
 * a flat trend runs across the middle.
 *   [0, 10] → "M0 26L120 2";  [0, 10, 5] → "M0 26L60 2L120 14";  [5, 5] → "M0 14L120 14"
 */
export function sparkPath(values: number[]): string {
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const span = SPARK_H - 2 * SPARK_PAD;
  const y = (v: number) => (hi === lo ? SPARK_H / 2 : SPARK_PAD + (1 - (v - lo) / (hi - lo)) * span);
  const x = (i: number) => (i / (values.length - 1)) * SPARK_W;
  const round = (n: number) => Math.round(n * 10) / 10;
  return values.map((v, i) => `${i ? "L" : "M"}${round(x(i))} ${round(y(v))}`).join("");
}
