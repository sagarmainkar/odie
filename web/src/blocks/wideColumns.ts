// Card grids (kpis, tiles, the grid container) on a wide screen. A phone always shows two columns. When the reply bubble
// (or #sample turn) holding the block is 576px or wider, a Tailwind container query (@xl, on the bubble's
// @container) spreads the cards out instead of letting them grow huge: the chat column on a tablet or a desktop. A
// phone's bubble is at most about 480px wide, so a phone never sees this.

/** The extra column class for a grid of `count` cards when its block is wide; "" keeps the phone's two columns.
 *  Worked examples: 2 kpis -> "" (two columns, as on a phone); 3 tiles -> three in a row; 4 kpis -> four in a row;
 *  6 tiles -> rows of three; 5 bars -> rows of three (three, then two). */
export function wideColumns(count: number): string {
  if (count === 3) return "@xl:grid-cols-3";
  if (count === 4) return "@xl:grid-cols-4";
  if (count >= 5) return "@xl:grid-cols-3";
  return "";
}
