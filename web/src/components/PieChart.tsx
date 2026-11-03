// Pie and donut: shares of a whole, with a legend beside the drawing (below it when the card is narrower than 440px)
// listing each slice's name, value and share, so no label is squeezed onto a slice.
import { useState } from "react";
import { fmt, partColour, seriesName, shareNote, sharePct, type ChartSpec } from "./chartData";
import { ChartTip, type Tip } from "./ChartTip";
import { pickKeys } from "./chartPick";

const BOX = 168, C = BOX / 2, OUTER = 80, HOLE = 52;  // the drawing's size and centre, the outer radius, a donut's hole

/** A point on the circle, at a fraction of a turn clockwise from 12 o'clock: (0, 80) -> top; (0.25, 80) -> right. */
function at(turn: number, r: number): [number, number] {
  const a = turn * 2 * Math.PI;
  return [+(C + r * Math.sin(a)).toFixed(2), +(C - r * Math.cos(a)).toFixed(2)];
}

/** One slice's outline from `start` to `end` (fractions of a turn): a wedge from the centre, or with a hole (a donut)
 *  a piece of the ring. A slice that is the whole circle stops just short of closing, or its arc would vanish. */
function slicePath(start: number, end: number, hole: number): string {
  const stop = Math.min(end, start + 0.9999);
  const large = stop - start > 0.5 ? 1 : 0;
  const [x1, y1] = at(start, OUTER);
  const [x2, y2] = at(stop, OUTER);
  if (hole === 0) return `M${C},${C} L${x1},${y1} A${OUTER},${OUTER} 0 ${large} 1 ${x2},${y2} Z`;
  const [x3, y3] = at(stop, hole);
  const [x4, y4] = at(start, hole);
  return `M${x1},${y1} A${OUTER},${OUTER} 0 ${large} 1 ${x2},${y2} L${x3},${y3} A${hole},${hole} 0 ${large} 0 ${x4},${y4} Z`;
}

/** A slice's name short enough for a donut's hole: "Fixed deposits" stays; "Equity mutual funds (large cap)" ->
 *  "Equity mutual f…". */
function shortLabel(label: string): string {
  if (label.length <= 15) return label;
  return `${label.slice(0, 14)}…`;
}

/** Which colour a slice gets: the chart palette in order, except an "Other" slice (the small ones merged, or the
 *  model's own), which is grey so it doesn't look like a category. ("Rent", 0) -> palette 1; ("Other", 5) -> grey. */
function sliceColour(label: string, i: number): string {
  if (label === "Other") return "var(--t-dim)";
  return partColour(i);
}

/**
 * Pie and donut, from x (the slices) and the first series (their values, all positive: parseChart saw to that). A
 * donut shows the total in its middle; a pie shows it above. Values in % are shares already, so their total (100%)
 * says nothing: the biggest slice is shown instead, and the legend leaves out the value column. Percentages are written
 * in the legend only, never on the slices. Pointing at a slice or its legend row (or stepping with the arrow keys)
 * fades the others and shows its hover card, with the value in full.
 */
export function PieChart({ spec }: { spec: ChartSpec }) {
  const [picked, setPicked] = useState<number | null>(null);
  const [tip, setTip] = useState<Tip | null>(null);
  const [drawingEl, setDrawingEl] = useState<SVGSVGElement | null>(null);  // the svg, once drawn: the card is placed by it
  const values = spec.series[0].data as number[];
  const total = values.reduce((sum, v) => sum + v, 0);
  const unit = spec.series[0].unit ?? spec.unit;
  const donut = spec.type === "donut";
  const hole = donut ? HOLE : 0;

  const slices: { start: number; end: number }[] = [];
  let start = 0;
  for (const v of values) {
    slices.push({ start, end: start + v / total });
    start += v / total;
  }

  const valuesAreShares = unit === "%";
  const biggest = values.indexOf(Math.max(...values));
  let headline = { value: fmt(total, unit), full: fmt(total, unit, { full: true }), label: "Total" };
  if (valuesAreShares) {
    const share = sharePct(values[biggest] / total);
    headline = { value: share, full: share, label: String(spec.x[biggest]) };
  }

  /** Picks slice i (or none) and points the hover card at the middle of its ring. */
  function pick(i: number | null) {
    setPicked(i);
    const el = drawingEl;
    const body = el?.parentElement;  // .chart-pie-body, which the card is placed in
    if (i === null || !el || !body) return setTip(null);
    const middle = (slices[i].start + slices[i].end) / 2;
    const radius = donut ? (OUTER + HOLE) / 2 : OUTER * 0.6;
    const [x, y] = at(middle, radius);
    const drawing = el.getBoundingClientRect();
    const around = body.getBoundingClientRect();
    const label = String(spec.x[i]);
    const note = valuesAreShares ? undefined : shareNote(values, values[i]);
    setTip({ x: drawing.left - around.left + x, y: drawing.top - around.top + y, title: label,
      rows: [{ colour: sliceColour(label, i), name: seriesName(spec.series, 0), value: fmt(values[i], unit, { full: true }) }], note });
  }
  const toggle = (i: number) => pick(picked === i ? null : i);
  const faded = (i: number) => (picked === null || picked === i ? 1 : 0.5);
  const mouse = (i: number | null) => (e: { pointerType: string }) => e.pointerType === "mouse" && pick(i);
  const headlineTitle = headline.full !== headline.value ? headline.full : undefined;

  return (
    <figure className="chart chart-pie glass glass-solid rounded-[26px] px-4 pt-4 pb-3 my-2">
      <figcaption className="text-[13px] font-semibold text-muted truncate">{spec.title ?? spec.series[0].name ?? "Chart"}</figcaption>
      {!donut && (
        <div className="flex items-baseline gap-2 mt-0.5 min-w-0">
          <span className="text-[30px] leading-tight font-extrabold tracking-[-0.03em] tabular-nums" title={headlineTitle}>{headline.value}</span>
          <span className="text-[12px] text-muted truncate">{headline.label}</span>
        </div>
      )}
      <div className="chart-pie-body">
        <svg ref={setDrawingEl} width={BOX} height={BOX} viewBox={`0 0 ${BOX} ${BOX}`} className="chart-pie-svg" role="img"
          aria-label={spec.title ?? "chart"} {...pickKeys(values.length, picked, pick)}>
          {slices.map((s, i) => (
            <path key={i} d={slicePath(s.start, s.end, hole)} fill={sliceColour(String(spec.x[i]), i)} opacity={faded(i)}
              className="chart-slice" onClick={() => toggle(i)} onPointerEnter={mouse(i)} onPointerLeave={mouse(null)} />
          ))}
          {donut && (
            <g textAnchor="middle" pointerEvents="none">
              <text x={C} y={C - 2} className="chart-pie-total"><title>{headline.full}</title>{headline.value}</text>
              <text x={C} y={C + 15} className="chart-axis">{shortLabel(headline.label)}</text>
            </g>
          )}
        </svg>
        <table className="chart-pie-legend">
          <tbody>
            {values.map((v, i) => (
              <tr key={i} onClick={() => toggle(i)} onPointerEnter={mouse(i)} onPointerLeave={mouse(null)} style={{ opacity: faded(i) }}>
                <td className="w-2.5"><i className="block w-2.5 h-2.5 mt-[4px] rounded-[3px]" style={{ background: sliceColour(String(spec.x[i]), i) }} /></td>
                <td className="w-full text-ink-2 [overflow-wrap:anywhere]">{spec.x[i]}</td>
                {!valuesAreShares && <td className="text-right font-semibold whitespace-nowrap">{fmt(v, unit)}</td>}
                <td className="text-right text-muted whitespace-nowrap">{sharePct(v / total)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <ChartTip tip={tip} />
      </div>
      {spec.source && <div className="text-[11px] text-dim text-right">{spec.source}</div>}
    </figure>
  );
}
