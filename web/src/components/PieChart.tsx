import { useState } from "react";
import { fmt, partColour, sharePct, type ChartSpec } from "./chartData";

const C = 100, OUTER = 96, HOLE = 62;  // drawn in a 200 x 200 box: the centre, the outer radius, a donut's hole

/** A point on the circle, at a fraction of a turn clockwise from 12 o'clock: (0, 96) -> top; (0.25, 96) -> right. */
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
 *  "Equity mutual fun…". */
function shortLabel(label: string): string {
  if (label.length <= 16) return label;
  return `${label.slice(0, 15)}…`;
}

/** Which colour a slice gets: the chart palette in order, except an "Other" slice (the small ones merged, or the
 *  model's own), which is grey so it doesn't look like a category. ("Rent", 0) -> palette 1; ("Other", 5) -> grey. */
function sliceColour(label: string, i: number): string {
  if (label === "Other") return "var(--t-dim)";
  return partColour(i);
}

/** Pie and donut: shares of a whole, from x (the slices) and the first series (their values, all positive: parseChart
 *  saw to that). Under it, a legend with each slice's share and value, so no label is squeezed onto a slice. A donut
 *  shows the total in its middle; a pie shows it above (values in %, a portfolio mix: the biggest slice instead).
 *  Tapping a slice or its legend row picks it: the others fade and the total gives way to that slice. */
export function PieChart({ spec }: { spec: ChartSpec }) {
  const [picked, setPicked] = useState<number | null>(null);
  const values = spec.series[0].data as number[];
  const total = values.reduce((sum, v) => sum + v, 0);
  const unit = spec.series[0].unit ?? spec.unit;
  const donut = spec.type === "donut";

  const slices: { start: number; end: number }[] = [];
  let start = 0;
  for (const v of values) {
    slices.push({ start, end: start + v / total });
    start += v / total;
  }

  // Values in % are shares already: their total says nothing (100%), and each one's value would repeat its share.
  const valuesAreShares = unit === "%";
  // What the big number shows: the picked slice; else the whole, or for shares the biggest slice.
  const biggest = values.indexOf(Math.max(...values));
  const featured = picked ?? (valuesAreShares ? biggest : null);
  const shownValue = featured === null ? total : values[featured];
  const shownLabel = featured === null ? "Total" : `${spec.x[featured]} · ${sharePct(values[featured] / total)}`;
  const middleText = featured === null ? fmt(total, unit) : sharePct(values[featured] / total);
  const middleSize = middleText.length > 8 ? 17 : 22;  // a long amount ("₹2,94,059 Cr") still fits the hole
  const toggle = (i: number) => setPicked(picked === i ? null : i);
  const faded = (i: number) => (picked === null || picked === i ? 1 : 0.35);

  return (
    <figure className="chart glass glass-solid rounded-[26px] px-4 pt-4 pb-3 my-2">
      <figcaption className="text-[13px] font-semibold text-muted truncate">{spec.title ?? spec.series[0].name ?? "Chart"}</figcaption>
      {!donut && (
        <div className="flex items-baseline gap-2 mt-0.5">
          <span className="text-[30px] leading-tight font-extrabold tracking-[-0.03em] tabular-nums">{fmt(shownValue, unit)}</span>
          <span className="text-[12px] text-muted truncate">{shownLabel}</span>
        </div>
      )}
      <svg viewBox="0 0 200 200" className="block w-full max-w-[200px] h-auto mx-auto mt-2 select-none" role="img" aria-label={spec.title ?? "chart"}>
        {slices.map((s, i) => (
          <path key={i} d={slicePath(s.start, s.end, donut ? HOLE : 0)} fill={sliceColour(String(spec.x[i]), i)} opacity={faded(i)}
            stroke="var(--t-surface-2)" strokeWidth="2" strokeLinejoin="round" className="cursor-pointer"
            onClick={() => toggle(i)} onPointerEnter={(e) => e.pointerType === "mouse" && setPicked(i)} onPointerLeave={(e) => e.pointerType === "mouse" && setPicked(null)} />
        ))}
        {donut && (
          <g textAnchor="middle" className="pointer-events-none">
            <text x={C} y={C + 2} fontSize={middleSize} fontWeight="800" fill="var(--t-ink)" className="tabular-nums">{middleText}</text>
            <text x={C} y={C + 22} fontSize="11.5" fill="var(--t-muted)">{featured === null ? "Total" : shortLabel(String(spec.x[featured]))}</text>
          </g>
        )}
      </svg>
      <table className="w-full mt-3 text-[13px] leading-[18px]">
        <tbody>
          {values.map((v, i) => (
            <tr key={i} onClick={() => toggle(i)} className="cursor-pointer" style={{ opacity: faded(i) }}>
              <td className="w-4 py-1 align-top"><i className="block w-2.5 h-2.5 mt-[4px] rounded-full" style={{ background: sliceColour(String(spec.x[i]), i) }} /></td>
              <td className="py-1 pr-2 text-ink-2 break-words">{spec.x[i]}</td>
              <td className="py-1 pr-2 text-right font-semibold tabular-nums whitespace-nowrap align-top">{sharePct(v / total)}</td>
              {!valuesAreShares && <td className="py-1 text-right text-muted tabular-nums whitespace-nowrap align-top">{fmt(v, unit)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
      {spec.source && <div className="text-[11px] text-dim text-right">{spec.source}</div>}
    </figure>
  );
}
