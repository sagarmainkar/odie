// Picking a point, bar or slice from the keyboard: every chart's drawing is focusable, the arrow keys step through
// what it shows and Escape (or leaving it) hides the hover card. The pointer picks in each drawing's own way.
import type { KeyboardEvent } from "react";

/**
 * Where a key moves the pick among n items: → the next, ← the one before (starting from the first or the last), held
 * at the ends; with `rows` (horizontal bars, read top to bottom) ↓ and ↑ too. Escape → null (nothing picked);
 * undefined for any other key, which is left to the browser.
 *   (null, "ArrowRight", 5) → 0;  (null, "ArrowLeft", 5) → 4;  (4, "ArrowRight", 5) → 4;  (3, "Escape", 5) → null
 */
export function stepPick(at: number | null, key: string, n: number, rows = false): number | null | undefined {
  const next = key === "ArrowRight" || (rows && key === "ArrowDown");
  const back = key === "ArrowLeft" || (rows && key === "ArrowUp");
  if (key === "Escape") return null;
  if (next) return at === null ? 0 : Math.min(n - 1, at + 1);
  if (back) return at === null ? n - 1 : Math.max(0, at - 1);
  return undefined;
}

/** The props that make a drawing focusable and steerable from the keyboard: spread them on its svg (or grid). */
export function pickKeys(n: number, at: number | null, pick: (i: number | null) => void, rows = false) {
  return {
    tabIndex: 0,
    onKeyDown: (e: KeyboardEvent) => {
      const next = stepPick(at, e.key, n, rows);
      if (next === undefined) return;
      e.preventDefault();
      pick(next);
    },
    onBlur: () => pick(null),
  };
}
