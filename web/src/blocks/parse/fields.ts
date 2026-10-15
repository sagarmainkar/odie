// Small readers every block parser shares: each takes one field as the model wrote it and returns something safe to
// draw, or undefined/null when the field is missing or unusable. Plus Trail, which records what was dropped and why.
import { plainMath } from "../../plainMath";
import { ICON_NAMES, type IconName } from "../../components/Tile";

/** A finite number, or null. 42 → 42; "42" → null; NaN → null. */
export function num(v: unknown): number | null {
  if (typeof v === "number" && isFinite(v)) return v;
  return null;
}

/** Trimmed text with LaTeX symbols turned into characters, cut to `max`; undefined when empty or not text.
 *  "  Pune $\rightarrow$ Goa " → "Pune → Goa" */
export function str(v: unknown, max = 120): string | undefined {
  if (typeof v !== "string") return undefined;
  const trimmed = v.trim();
  if (!trimmed) return undefined;
  return plainMath(trimmed).slice(0, max);
}

/** Like str, but a number counts too (table cells, list values): 4.6 → "4.6". */
export function textOrNumber(v: unknown, max = 120): string | undefined {
  if (num(v) !== null) return String(v);
  return str(v, max);
}

/** The first of several fields that holds usable text. Models name the same thing differently, so a parser asks
 *  for the canonical field first and its aliases after: firstText([item.title, item.name], 80). */
export function firstText(values: unknown[], max = 120): string | undefined {
  for (const v of values) {
    const found = str(v, max);
    if (found !== undefined) return found;
  }
  return undefined;
}

/** firstText, but a number counts too: firstTextOrNumber([item.value, item.rating]) with rating 4.6 → "4.6". */
export function firstTextOrNumber(values: unknown[], max = 120): string | undefined {
  for (const v of values) {
    const found = textOrNumber(v, max);
    if (found !== undefined) return found;
  }
  return undefined;
}

/** The first of several fields that is a list (same idea as firstText): firstList([raw.items, raw.rows]). */
export function firstList(values: unknown[]): unknown[] | undefined {
  return values.find((v) => Array.isArray(v)) as unknown[] | undefined;
}

/** One of the app's icon names, or undefined. "plane" → "plane"; "aeroplane" → undefined. */
export function icon(v: unknown): IconName | undefined {
  if ((ICON_NAMES as string[]).includes(v as string)) return v as IconName;
  return undefined;
}

/** An https link, or undefined (http, javascript: and the rest are refused). */
export function https(v: unknown): string | undefined {
  if (typeof v === "string" && /^https:\/\//.test(v)) return v;
  return undefined;
}

/** The object without its undefined fields, so a parsed block holds only what the model gave. */
export function clean<T extends object>(o: T): T {
  return Object.fromEntries(Object.entries(o).filter(([, v]) => v !== undefined)) as T;
}

/** A thing the parser dropped: where it was in the fence and why. {path: "1.rows.2", why: "row has 5 cells, table has 4 columns"} */
export type Diagnostic = { path: string; why: string };

/** Where the parser is in the fence ("1.rows.2") and the shared list of what it dropped. A parser that gives up writes
 *  `return here.drop("why")`, which notes the reason and returns null. */
export class Trail {
  readonly path: string;
  readonly dropped: Diagnostic[];

  constructor(path = "", dropped: Diagnostic[] = []) {
    this.path = path;
    this.dropped = dropped;
  }

  /** One step deeper: new Trail("1").at("rows").at(2).path → "1.rows.2" */
  at(step: string | number): Trail {
    const path = this.path ? `${this.path}.${step}` : String(step);
    return new Trail(path, this.dropped);
  }

  drop(why: string): null {
    this.dropped.push({ path: this.path, why });
    return null;
  }
}

/** The first `max` items of a list; when there are more, a note says how many were left out. */
export function keepFirst<T>(items: T[], max: number, here: Trail, what: string): T[] {
  if (items.length > max) here.drop(`kept the first ${max} ${what} of ${items.length}`);
  return items.slice(0, max);
}
