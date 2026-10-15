// The chart's drawing width (ChartBlock.tsx); its own file so the component file exports only components.

const BASE_W = 320;  // a phone's drawing width, scaled to fit

/** The width the chart is drawn in (its viewBox), from the width it takes on screen. Up to 480px (every phone) it is
 *  drawn 320 wide and scaled to fit, as always. Wider (a tablet or desktop chat column) it is drawn at its real width
 *  at a fixed 1.3x, so the bars spread out sideways while the labels and the height stay near a phone's size, instead
 *  of the whole drawing growing with the column.
 *  Worked examples: 300 -> 320 (a phone); 480 -> 320; 740 -> 569 (shown 195px tall, labels about 14px); 0 (not
 *  measured yet) -> 320. */
export function drawWidth(shownWidth: number): number {
  if (shownWidth <= 480) return BASE_W;
  return Math.round(shownWidth / 1.3);
}
