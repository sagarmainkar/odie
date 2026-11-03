import { keepFirst, num, str, type Trail } from "./fields";

export type KpiItem = {
  label: string; value: number | string | null; unit?: string; change?: number | null; change_unit?: "%" | "pt";
  /** A small line under the number (Kpis.tsx), oldest first. */
  trend?: number[];
};

// A trend needs 2 points to be a line, and more than 60 would not show in a card's width.
const TREND_FEWEST = 2;
const TREND_MOST = 60;
export type KpisBlock = { type: "kpis"; items: KpiItem[] };

/**
 * One headline number (a kpis item, or a stat atom). The label must be text; the value may be a number or short text
 * ("Leeds United (H)"); change_unit is "pt" only when the model says so, otherwise "%". trend: see readTrend; a
 * bad one is left out, never the card.
 *   {label: "Revenue", value: 72275, unit: "₹Cr", change: 2.2} → {label: "Revenue", value: 72275, unit: "₹Cr", change: 2.2, change_unit: "%"}
 *   {label: "TCS", value: 3082, trend: [3290, 3150, 3082]} → {..., trend: [3290, 3150, 3082]}
 */
export function readKpi(item: any): KpiItem {
  let value: number | string | null = num(item.value);
  if (value === null) value = str(item.value, 40) ?? null;
  const unit = typeof item.unit === "string" ? item.unit : undefined;
  const changeUnit = item.change_unit === "pt" ? "pt" : "%";
  const kpi: KpiItem = { label: item.label, value, unit, change: num(item.change), change_unit: changeUnit };
  const trend = readTrend(item.trend);
  if (trend) kpi.trend = trend;
  return kpi;
}

/**
 * A trend's finite numbers, the latest 60 at most; undefined (no line) when fewer than 2 are left or it isn't a list.
 *   [100, "90", null, 85, 80] → [100, 85, 80];  [5, "6"] → undefined;  "1,2,3" → undefined;  70 numbers → the last 60
 */
function readTrend(v: unknown): number[] | undefined {
  if (!Array.isArray(v)) return undefined;
  const numbers = v.map(num).filter((n): n is number => n !== null);
  if (numbers.length < TREND_FEWEST) return undefined;
  return numbers.slice(-TREND_MOST);
}

/**
 * kpis: up to 4 headline numbers in cards. Items without a text label are dropped.
 *   {type: "kpis", items: [{label: "Steps", value: 8200}, {value: 3}]} → {type: "kpis", items: [{label: "Steps", value: 8200, …}]}
 * Dropped: no items list, or no item with a label.
 */
export function readKpis(raw: any, here: Trail): KpisBlock | null {
  if (!Array.isArray(raw.items)) return here.drop("kpis needs items");
  const items: KpiItem[] = [];
  raw.items.forEach((item: any, i: number) => {
    if (!item || typeof item.label !== "string") {
      here.at("items").at(i).drop("item has no label");
      return;
    }
    items.push(readKpi(item));
  });
  if (!items.length) return here.drop("kpis has no item with a label");
  return { type: "kpis", items: keepFirst(items, 4, here, "items") };
}
