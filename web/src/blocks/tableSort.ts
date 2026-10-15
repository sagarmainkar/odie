import { plainInline } from "./inlineSyntax";

export type SortState = { column: number; direction: "up" | "down" } | null;

/**
 * The number a cell starts with, for sorting and right-aligning: up to three leading symbols (₹, $, "Rs ") are
 * allowed, commas ignored. "₹44,999" → 44999; "4,800 mAh" → 4800; "4.6★" → 4.6; "Pixel 10a" → null; "" → null.
 */
export function cellNumber(cell: string): number | null {
  const plain = plainInline(cell).replace(/,/g, "");
  const m = /^[^\d\-+]{0,3}([-+]?\d+(?:\.\d+)?)/.exec(plain);
  if (!m) return null;
  return Number(m[1]);
}

/**
 * The order to show rows in (indices into rows) when sorted by one column. Numbers compare as numbers, text
 * alphabetically (with numbers inside text in order: "Day 2" before "Day 10"); blank cells always go last.
 *   rows [["A", "₹300"], ["B", ""], ["C", "₹50"]], {column: 1, direction: "up"} → [2, 0, 1]
 * With no sort, the model's order: [0, 1, 2].
 */
export function sortedOrder(rows: string[][], sort: SortState): number[] {
  const order = rows.map((_, i) => i);
  if (!sort) return order;
  const sign = sort.direction === "up" ? 1 : -1;
  return order.sort((a, b) => {
    const left = rows[a][sort.column] ?? "";
    const right = rows[b][sort.column] ?? "";
    if (!left || !right) return blanksLast(left, right);
    return sign * compareCells(left, right);
  });
}

function blanksLast(left: string, right: string): number {
  if (!left && !right) return 0;
  if (!left) return 1;
  return -1;
}

function compareCells(left: string, right: string): number {
  const a = cellNumber(left);
  const b = cellNumber(right);
  if (a !== null && b !== null) return a - b;
  return plainInline(left).localeCompare(plainInline(right), undefined, { numeric: true, sensitivity: "base" });
}

/** A tap on a column header: not sorted → up → down → back to the model's order. */
export function nextSort(sort: SortState, column: number): SortState {
  if (!sort || sort.column !== column) return { column, direction: "up" };
  if (sort.direction === "up") return { column, direction: "down" };
  return null;
}

/** A column reads as numbers (right-aligned) when every filled cell starts with one. */
export function isNumberColumn(rows: string[][], column: number): boolean {
  const filled = rows.map((r) => r[column]).filter((cell) => cell);
  return filled.length > 0 && filled.every((cell) => cellNumber(cell) !== null);
}
