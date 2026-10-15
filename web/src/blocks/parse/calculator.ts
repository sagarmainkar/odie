import { isHelper, namesIn, parseFormula } from "../formula";
import { clean, firstList, firstText, keepFirst, num, type Trail } from "./fields";

export type CalcInput = { id: string; label: string; min: number; max: number; step: number; value: number; unit?: string };
export type CalcOutput = { label: string; formula: string; unit?: string };
export type CalculatorBlock = { type: "calculator"; title?: string; inputs: CalcInput[]; outputs: CalcOutput[] };

const MAX_INPUTS = 6;
const MAX_OUTPUTS = 6;
const ID = /^[A-Za-z_][A-Za-z0-9_]{0,23}$/;

/**
 * calculator: sliders for what-if numbers, with results worked out again as they move (see formula.ts).
 * - inputs (also `sliders`), up to 6: {id (also `name`/`key`): a short name the formulas use, label (also `title`),
 *   min (default 0), max (default twice the value, or 100), step (default about 1/100 of the range), value (also
 *   `default`; kept between min and max, default min), unit}. A helper's name (emi, min…) can't be an id.
 * - outputs (also `results`), up to 6: {label, formula (also `expr`/`value`), unit}. A formula that can't be read is
 *   kept (it shows "–") and noted, so the eval sees it.
 * - title: optional.
 *   {type: "calculator", sliders: [{name: "p", title: "Loan", max: 10000000, default: 4000000, unit: "₹"}],
 *    results: [{label: "EMI", expr: "emi(p, 8.5, 20)", unit: "₹"}]}
 *   → {type: "calculator", inputs: [{id: "p", label: "Loan", min: 0, max: 10000000, step: 100000, value: 4000000, unit: "₹"}],
 *      outputs: [{label: "EMI", formula: "emi(p, 8.5, 20)", unit: "₹"}]}
 * Dropped: no usable input (and each input or output that can't be used, with a note).
 */
export function readCalculator(raw: any, here: Trail): CalculatorBlock | null {
  const inputs: CalcInput[] = [];
  const rawInputs = firstList([raw.inputs, raw.sliders]) ?? [];
  rawInputs.forEach((item, i) => {
    const where = here.at("inputs").at(i);
    const input = readInput(item, where);
    if (!input) return;
    if (inputs.some((x) => x.id === input.id)) {
      where.drop(`input id "${input.id}" is used twice`);
      return;
    }
    inputs.push(input);
  });
  if (!inputs.length) return here.drop("calculator has no usable input");
  const kept = keepFirst(inputs, MAX_INPUTS, here, "inputs");

  const outputs: CalcOutput[] = [];
  const ids = kept.map((x) => x.id);
  const rawOutputs = firstList([raw.outputs, raw.results]) ?? [];
  rawOutputs.forEach((item, i) => {
    const output = readOutput(item, ids, here.at("outputs").at(i));
    if (output) outputs.push(output);
  });

  const title = firstText([raw.title], 80);
  return clean({ type: "calculator" as const, title, inputs: kept, outputs: keepFirst(outputs, MAX_OUTPUTS, here, "outputs") });
}

/** One slider; null (with a note) when it has no usable id or label, or its range is empty. */
function readInput(item: any, here: Trail): CalcInput | null {
  if (!item || typeof item !== "object") return here.drop("input is not an object");
  const id = firstText([item.id, item.name, item.key], 24);
  if (!id || !ID.test(id) || isHelper(id)) return here.drop(`input needs an id like "p" or "rate" (got ${JSON.stringify(id ?? null)})`);
  const label = firstText([item.label, item.title], 40) ?? id;
  const given = num(item.value) ?? num(item.default);

  const min = num(item.min) ?? 0;
  let max = num(item.max);
  if (max === null) max = defaultMax(given);
  if (max <= min) return here.drop("input's max must be above its min");
  const step = positive(num(item.step)) ?? niceStep((max - min) / 100);
  const value = Math.min(max, Math.max(min, given ?? min));
  const unit = firstText([item.unit], 12);
  return clean({ id, label, min, max, step, value, unit });
}

/** One result line; null (with a note) when it has no label or no formula. A formula that can't be read, or that uses
 *  a name no input has, is kept (it will show "–") with a note. */
function readOutput(item: any, ids: string[], here: Trail): CalcOutput | null {
  if (!item || typeof item !== "object") return here.drop("output is not an object");
  const label = firstText([item.label, item.title, item.name], 40);
  const formula = firstText([item.formula, item.expr, item.value], 300);
  if (!label || !formula) return here.drop("output needs a label and a formula");
  try {
    const unknown = namesIn(parseFormula(formula)).filter((name) => !ids.includes(name));
    if (unknown.length) here.drop(`formula uses ${unknown.join(", ")}, which no input has; shows –`);
  } catch (e) {
    here.drop(`formula can't be read (${(e as Error).message}); shows –`);
  }
  return clean({ label, formula, unit: firstText([item.unit], 12) });
}

/** A max when the model gave none: twice the starting value, or 100. 4000000 → 8000000; none or 0 → 100 */
function defaultMax(value: number | null): number {
  if (value !== null && value > 0) return value * 2;
  return 100;
}

function positive(v: number | null): number | null {
  if (v !== null && v > 0) return v;
  return null;
}

/** A round step near `rough`: 1, 2 or 5 times a power of ten. 90000 → 100000; 0.27 → 0.2; 7 → 5 */
export function niceStep(rough: number): number {
  const power = 10 ** Math.floor(Math.log10(rough));
  const scaled = rough / power;
  if (scaled < 1.5) return power;
  if (scaled < 3.5) return 2 * power;
  if (scaled < 7.5) return 5 * power;
  return 10 * power;
}
