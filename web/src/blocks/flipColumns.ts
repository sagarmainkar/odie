// How many columns a set of flash cards (Flip.tsx) is laid out in on a wide screen. Its own file so the component
// file exports only components.

/** All in one row up to 4 cards, then 3 or 4 columns, whichever leaves the last row fullest (a tie goes to 4), so the
 *  last row is never one card on its own. A phone uses two columns instead (styles.css, .flip-grid).
 *  4 → 4;  5 → 3 (3 + 2, not 4 + 1);  6 → 3;  7 → 4 (4 + 3);  8 → 4;  9 → 3;  10 → 4 (4 + 4 + 2, not 3 + 3 + 3 + 1) */
export function flipColumns(cards: number): number {
  if (cards <= 4) return Math.max(1, cards);
  const lastRowShare = (columns: number) => (cards % columns || columns) / columns;
  if (lastRowShare(3) > lastRowShare(4)) return 3;
  return 4;
}
