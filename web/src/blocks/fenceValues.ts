// Shared values: a calculator's inputs belong to the whole fence they're in. Their current values work in the
// calculator's formulas and, as {formula} placeholders, in any text in the same fence: "Monthly: {emi(p, r, n)}" or
// just "{n} years". Values live only on screen, one set per fence; nothing is saved and nothing calls the model.
import { createContext } from "react";
import { userLocale } from "../locale";
import { evaluate, parseFormula } from "./formula";
import { formatAmount, type Block } from "./parse";

export type FenceValueState = { values: ReadonlyMap<string, number>; set: (id: string, value: number) => void };

/** The fence's input values and how to move one. Outside a fence with a calculator: no values, so text stays as written. */
export const FenceValues = createContext<FenceValueState>({ values: new Map(), set: () => {} });

/** Every calculator input in the fence (inside containers too) with the value the model gave it. When two
 *  calculators use the same id, the first one's wins.
 *   [{type: "calculator", inputs: [{id: "p", value: 4000000, …}]}, {type: "text", …}] → Map {p → 4000000} */
export function startingValues(blocks: Block[], found: Map<string, number> = new Map()): Map<string, number> {
  for (const block of blocks) {
    if (block.type === "calculator") {
      for (const input of block.inputs) {
        if (!found.has(input.id)) found.set(input.id, input.value);
      }
    }
    if ("children" in block) startingValues(block.children, found);
  }
  return found;
}

// {formula}, but not a badge's colour: in ":badge[Sold out]{warn}" the {warn} follows "]" and is left alone.
const PLACEHOLDER = /(?<!\])\{([^{}\n]{1,200})\}/g;

/**
 * Text with each {formula} replaced by its value now. Only in a fence that has values: elsewhere text is left as
 * written, braces and all. A {…} that isn't a formula stays as written; one that can't be worked out (it divides by
 * zero, or names no input) shows "–".
 *   "EMI {round(emi(p, r, n))} for {n} years" with p = 4000000, r = 8.5, n = 20 → "EMI 34,713 for 20 years"
 *   "{hello there}" → "{hello there}"
 */
export function fillValues(text: string, values: ReadonlyMap<string, number>): string {
  if (values.size === 0 || !text.includes("{")) return text;
  return text.replace(PLACEHOLDER, (whole, formula: string, at: number) => {
    try {
      parseFormula(formula);
    } catch {
      return whole;
    }
    const value = evaluate(formula, values);
    if (value === null) return "–";
    return formatNumber(value, localeAfter(text.slice(0, at)));
  });
}

/** The grouping for a number written right after `before`: rupees always group the Indian way (as in the kpis block),
 *  anything else the user's way. "Total ₹" → "en-IN";  "Over " → the user's locale */
function localeAfter(before: string): string {
  if (before.endsWith("₹")) return "en-IN";
  return userLocale();
}

/** A number the way the user reads them (Indian grouping on an Indian install): 4000000 → "40,00,000";
 *  8.5 → "8.5"; 34712.9 → "34,713" (no decimals from 1,000 up, at most two below 100). */
export function formatNumber(v: number, locale: string = userLocale()): string {
  const abs = Math.abs(v);
  let digits = 2;
  if (abs >= 100) digits = 1;
  if (abs >= 1000) digits = 0;
  return v.toLocaleString(locale, { maximumFractionDigits: digits });
}

/** A value with its unit: money like the kpis block (₹ groups Indian-style), % stuck on, any other unit after a space
 *  (one of a plural word drops its "s").
 *   (34712.9, "₹") → "₹34,713";  (8.5, "%") → "8.5%";  (20, "years") → "20 years";  (1, "years") → "1 year";  (3, undefined) → "3" */
export function formatWithUnit(v: number, unit: string | undefined): string {
  const money = formatAmount(v, unit);
  if (money !== null) return money;
  const n = formatNumber(v);
  if (unit === "%") return `${n}%`;
  if (!unit) return n;
  const isPluralWord = /^[a-z]{3,}s$/i.test(unit);
  if (v === 1 && isPluralWord) return `${n} ${unit.slice(0, -1)}`;
  return `${n} ${unit}`;
}
