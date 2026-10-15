import { keepFirst, num, str, type Trail } from "./fields";

export type KpiItem = { label: string; value: number | string | null; unit?: string; change?: number | null; change_unit?: "%" | "pt" };
export type KpisBlock = { type: "kpis"; items: KpiItem[] };

/**
 * One headline number (a kpis item, or a stat atom). The label must be text; the value may be a number or short text
 * ("Leeds United (H)"); change_unit is "pt" only when the model says so, otherwise "%".
 *   {label: "Revenue", value: 72275, unit: "₹Cr", change: 2.2} → {label: "Revenue", value: 72275, unit: "₹Cr", change: 2.2, change_unit: "%"}
 */
export function readKpi(item: any): KpiItem {
  let value: number | string | null = num(item.value);
  if (value === null) value = str(item.value, 40) ?? null;
  const unit = typeof item.unit === "string" ? item.unit : undefined;
  const changeUnit = item.change_unit === "pt" ? "pt" : "%";
  return { label: item.label, value, unit, change: num(item.change), change_unit: changeUnit };
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
