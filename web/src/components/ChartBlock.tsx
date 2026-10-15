import { useEffect, useId, useMemo, useRef, useState } from "react";
import { drawWidth } from "./chartWidth";
import {
  chartKind, chartScales, fmt, isOnRightScale, maxSeries, partColour, pieSlices, stackSeries, totalAt,
  type Band, type ChartKind, type ChartSeries, type ChartSpec,
} from "./chartData";
import { ChartLegend } from "./ChartLegend";
import { HBarChart } from "./HBarChart";
import { PieChart } from "./PieChart";
import { readJson } from "../blocks/parse/lenientJson";

export type { ChartSpec } from "./chartData";

/** Parse a ```odie-chart block, or a chart block with its kind as `type`. Returns null when it isn't a usable chart
 *  (caller shows the text instead).
 *  type: line, bar, area, stacked, hbar, combo, pie or donut (chartKind); any other, or none, draws a line (a whole
 *  chart block, type "chart", has it in `kind`: DeepSeek V4.1 wrote one into a chart fence on 2026-10-12). Up to 3
 *  series (stacked and area 6); a value that isn't a number is a gap (null).
 *  Pie and donut: x names the slices and the first series holds their values (other series are ignored). Zero,
 *  negative and missing values are dropped (a share of a whole can't be any of those), and past 8 slices the smallest
 *  are merged into one "Other" (pieSlices). Nothing positive left: null.
 *  Combo: the first series is drawn as bars, the others as lines. A line with its own `unit`, unlike the chart's, or
 *  with `axis: "right"`, gets a scale of its own on the right:
 *    {"type": "combo", "unit": "₹Cr", "x": ["Q1", "Q2"], "series": [{"name": "Revenue", "data": [65799, 67087]},
 *                                                               {"name": "Margin", "unit": "%", "data": [18.4, 16]}]} */
export function parseChart(text: string): ChartSpec | null {
  const d: any = readJson(text);  // JSON, with the slips models make mended (numbers with thousands commas)
  if (!d || typeof d !== "object" || !Array.isArray(d.x) || !Array.isArray(d.series) || !d.series.length) return null;
  // A chart block written into a chart fence names its kind in `kind`: {"type": "chart", "kind": "hbar"} -> hbar.
  const kindName = d.type === "chart" ? d.kind : d.type;
  const type = chartKind(kindName);
  const unit = typeof d.unit === "string" ? d.unit : undefined;
  let x: string[] = d.x.map(String);
  let series: ChartSeries[] = d.series
    .filter((s: any) => s && Array.isArray(s.data))
    .slice(0, maxSeries(type))
    .map((s: any, k: number) => readSeries(s, k, type, unit));
  if (!series.length || series.every((s) => s.data.every((v) => v === null))) return null;
  if (type === "pie" || type === "donut") {
    const slices = pieSlices(x, series[0].data);
    if (!slices.x.length) return null;
    x = slices.x;
    series = [{ ...series[0], data: slices.data }];
  }
  return { type, title: typeof d.title === "string" ? d.title : undefined, x,
    series, unit, source: typeof d.source === "string" ? d.source : undefined };
}

/** One series as the model wrote it → its name, its numbers (anything else a gap), its own unit, its scale. */
function readSeries(s: any, k: number, type: ChartKind, chartUnit: string | undefined): ChartSeries {
  const name = typeof s.name === "string" ? s.name : undefined;
  const data = s.data.map((v: any) => (typeof v === "number" && isFinite(v) ? v : null));
  const unit = typeof s.unit === "string" ? s.unit : undefined;
  const right = isOnRightScale(type, k, unit, s.axis, chartUnit);
  return { name, data, unit, right };
}

const H = 150, L = 8, R = 8, T = 12, B = 22;
const SERIES = ["", "var(--t-dim)", "var(--t-line-2)"];  // series 0 uses the iris gradient

/** First to last value as a percentage (nulls skipped); null when there's nothing to compare. */
export function changePct(data: (number | null)[]): number | null {
  const v = data.filter((x): x is number => x !== null);
  if (v.length < 2 || v[0] === 0) return null;
  return ((v[v.length - 1] - v[0]) / Math.abs(v[0])) * 100;
}

/** A smooth line through the points (Catmull-Rom as cubic Béziers). */
export function smoothPath(pts: [number, number][]): string {
  if (!pts.length) return "";
  const f = (n: number) => +n.toFixed(1);
  let d = `M${f(pts[0][0])},${f(pts[0][1])}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] ?? pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] ?? p2;
    d += ` C${f(p1[0] + (p2[0] - p0[0]) / 6)},${f(p1[1] + (p2[1] - p0[1]) / 6)} ${f(p2[0] - (p3[0] - p1[0]) / 6)},${f(p2[1] - (p3[1] - p1[1]) / 6)} ${f(p2[0])},${f(p2[1])}`;
  }
  return d;
}

/** A chart of any kind: pies and donuts, and horizontal bars, have drawings of their own; the rest go up and down. */
export function ChartBlock({ spec }: { spec: ChartSpec }) {
  if (spec.type === "pie" || spec.type === "donut") return <PieChart spec={spec} />;
  if (spec.type === "hbar") return <HBarChart spec={spec} />;
  return <XYChart spec={spec} />;
}

/** Line, bar, area, stacked and combo: x labels along the bottom, values up the side. */
function XYChart({ spec }: { spec: ChartSpec }) {
  const [hover, setHover] = useState<number | null>(null);
  const svg = useRef<SVGSVGElement>(null);
  const [shownWidth, setShownWidth] = useState(0);
  useEffect(() => {  // follow the drawing's width on screen (the window resized, the chat column changed)
    const el = svg.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const watcher = new ResizeObserver(() => setShownWidth(el.getBoundingClientRect().width));
    watcher.observe(el);
    return () => watcher.disconnect();
  }, []);
  const W = drawWidth(shownWidth);
  const gid = useId().replace(/[^a-zA-Z0-9]/g, "");
  const n = spec.x.length;
  const slotted = spec.type === "bar" || spec.type === "stacked" || spec.type === "combo";  // each label owns a column
  const piled = spec.type === "stacked" || spec.type === "area";  // the series pile on each other
  const bands = useMemo(() => (piled ? stackSeries(spec.series, n) : null), [spec, n, piled]);
  const scales = useMemo(() => chartScales(spec, bands), [spec, bands]);
  const { min, max } = scales.left;
  const slot = (W - L - R) / n;
  const xAt = (i: number) => slotted ? L + slot * (i + 0.5) : L + (n === 1 ? (W - L - R) / 2 : ((W - L - R) * i) / (n - 1));
  const yAt = (v: number) => T + (H - T - B) * (1 - (v - min) / (max - min || 1));
  const yRight = (v: number) => {
    if (!scales.right) return yAt(v);
    const r = scales.right;
    return T + (H - T - B) * (1 - (v - r.min) / (r.max - r.min || 1));
  };
  const yOf = (s: ChartSeries) => (s.right ? yRight : yAt);
  const unitOf = (s: ChartSeries) => s.unit ?? spec.unit;
  const pct = spec.type === "line" ? changePct(spec.series[0].data) : null;
  const lastIdx = (() => { const d = spec.series[0].data; for (let i = d.length - 1; i >= 0; i--) if (d[i] !== null) return i; return n - 1; })();
  const shown = hover ?? lastIdx;
  // The big number: the whole pile for stacked bars and areas, else the first series.
  const big = piled ? totalAt(spec.series, shown) : spec.series[0].data[shown];
  const bigUnit = piled ? spec.unit : unitOf(spec.series[0]);
  // The small numbers beside it: the other series (a pile's parts have theirs in the legend, where there's room).
  const listed = piled ? [] : spec.series.slice(1);
  const peak = spec.type === "bar" ? spec.series[0].data.reduce<number>((best, v, i, a) => (v !== null && (a[best] === null || v > (a[best] as number)) ? i : best), 0) : -1;
  const faded = (i: number) => (hover === null || hover === i ? 1 : 0.45);  // the other columns while one is picked

  function pick(clientX: number) {
    const r = svg.current?.getBoundingClientRect(); if (!r) return;
    const x = ((clientX - r.left) / r.width) * W;
    let best = 0, dist = Infinity;
    for (let i = 0; i < n; i++) { const d = Math.abs(xAt(i) - x); if (d < dist) { dist = d; best = i; } }
    setHover(best);
  }

  return (
    <figure className="chart glass glass-solid rounded-[26px] px-4 pt-4 pb-3 my-2">
      <figcaption className="flex items-center justify-between gap-2">
        <span className="text-[13px] font-semibold text-muted truncate">{spec.title ?? spec.series[0].name ?? "Chart"}</span>
        {pct !== null && <span className={`chip ${pct >= 0 ? "chip-good" : "chip-warn"}`}>{pct >= 0 ? "▲" : "▼"} {Math.abs(pct).toFixed(1)}%</span>}
      </figcaption>
      <div className="flex items-baseline gap-2 mt-0.5">
        <span className="text-[30px] leading-tight font-extrabold tracking-[-0.03em] tabular-nums">{big === null || big === undefined ? "–" : fmt(big, bigUnit)}</span>
        <span className="text-[12px] text-muted tabular-nums truncate">
          {hover !== null ? spec.x[shown] : ""}
          {listed.map((s, k) => s.data[shown] === null || s.data[shown] === undefined ? null : <span key={k} className="ml-2">{s.name ? `${s.name} ` : ""}{fmt(s.data[shown] as number, unitOf(s))}</span>)}
        </span>
      </div>
      <svg ref={svg} viewBox={`0 0 ${W} ${H}`} className="w-full h-auto touch-none select-none mt-1 overflow-visible" role="img" aria-label={spec.title ?? "chart"}
        onPointerDown={(e) => pick(e.clientX)} onPointerMove={(e) => (e.buttons || e.pointerType === "mouse") && pick(e.clientX)} onPointerLeave={() => setHover(null)}>
        <defs>
          <linearGradient id={`fill-${gid}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#8a7dff" stopOpacity=".35" /><stop offset="1" stopColor="#8a7dff" stopOpacity="0" /></linearGradient>
          <linearGradient id={`stroke-${gid}`} x1="0" x2="1" y1="0" y2="0"><stop offset="0" stopColor="#7d8cff" /><stop offset=".6" stopColor="#b08bff" /><stop offset="1" stopColor="#ff8cc0" /></linearGradient>
          <linearGradient id={`bar-${gid}`} x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor="#b08bff" /><stop offset="1" stopColor="#7d8cff" /></linearGradient>
        </defs>
        {[0, n - 1].filter((i, k, a) => a.indexOf(i) === k).map((i) => (
          <text key={i} x={xAt(i)} y={H - 5} textAnchor={slotted ? "middle" : i === 0 ? "start" : "end"} fontSize="11" fill="var(--t-dim)">{String(spec.x[i])}</text>
        ))}
        {spec.type === "bar" && spec.series.map((s, k) => {
          const bw = (slot * 0.62) / spec.series.length;
          return s.data.map((v, i) => v === null ? null : (
            <rect key={`${k}-${i}`} x={xAt(i) - slot * 0.31 + k * bw} y={Math.min(yAt(v), yAt(0))} width={Math.max(bw - 2, 3)}
              height={Math.max(Math.abs(yAt(0) - yAt(v)), 2)} rx={Math.min(8, bw / 2)}
              fill={k === 0 && (hover === null ? i === peak : i === hover) ? `url(#bar-${gid})` : k === 0 ? "var(--t-line-2)" : SERIES[k]} />
          ));
        })}
        {spec.type === "line" && spec.series.map((s, k) => {
          const pts = s.data.map((v, i) => (v === null ? null : [xAt(i), yAt(v)] as [number, number])).filter(Boolean) as [number, number][];
          if (!pts.length) return null;
          const d = smoothPath(pts);
          return (
            <g key={k}>
              {k === 0 && <path d={`${d} L${pts[pts.length - 1][0]},${H - B} L${pts[0][0]},${H - B} Z`} fill={`url(#fill-${gid})`} />}
              {k === 0
                ? <path d={d} fill="none" stroke={`url(#stroke-${gid})`} strokeWidth="3" strokeLinecap="round" pathLength={1} strokeDasharray="1" strokeDashoffset="1" className="chart-draw" />
                : <path d={d} fill="none" stroke={SERIES[k]} strokeWidth="2" strokeLinecap="round" />}
            </g>
          );
        })}
        {spec.type === "stacked" && bands && bands.map((partBands, k) => partBands.map((b, i) => b === null || b.from === b.to ? null : (
          // each part 2px shorter than its band, so the parts sit apart; a zero part isn't drawn
          <rect key={`${k}-${i}`} x={xAt(i) - slot * 0.31} y={Math.min(yAt(b.from), yAt(b.to))} width={Math.max(slot * 0.62, 3)}
            height={Math.max(Math.abs(yAt(b.from) - yAt(b.to)) - 2, 1)} rx="3" fill={partColour(k)} opacity={faded(i)} />
        )))}
        {spec.type === "area" && bands && bands.map((partBands, k) => <Area key={k} bands={partBands} xAt={xAt} yAt={yAt} colour={partColour(k)} />)}
        {spec.type === "combo" && (
          <g>
            {spec.series[0].data.map((v, i) => v === null ? null : (
              <rect key={i} x={xAt(i) - slot * 0.31} y={Math.min(yAt(v), yAt(0))} width={Math.max(slot * 0.62, 3)}
                height={Math.max(Math.abs(yAt(0) - yAt(v)), 2)} rx={Math.min(6, slot * 0.31)} fill={partColour(0)} opacity={faded(i)} />
            ))}
            {spec.series.slice(1).map((s, j) => <ComboLine key={j} data={s.data} xAt={xAt} yAt={yOf(s)} colour={partColour(j + 1)} />)}
          </g>
        )}
        {(spec.type === "area" || spec.type === "combo") && hover !== null && (
          <line x1={xAt(shown)} x2={xAt(shown)} y1={T} y2={H - B} stroke="var(--t-dim)" strokeDasharray="3 4" />
        )}
        {spec.type === "line" && spec.series[0].data[shown] !== null && (hover !== null ? (
          <g>
            <line x1={xAt(shown)} x2={xAt(shown)} y1={T} y2={H - B} stroke="var(--t-dim)" strokeDasharray="3 4" />
            <circle cx={xAt(shown)} cy={yAt(spec.series[0].data[shown] as number)} r="6" fill="#fff" stroke="#8a7dff" strokeWidth="3" />
          </g>
        ) : (
          <circle cx={xAt(shown)} cy={yAt(spec.series[0].data[shown] as number)} r="5" fill="#ff8cc0" className="chart-pulse" />
        ))}
      </svg>
      {spec.type === "combo" && <ChartLegend series={spec.series} />}
      {piled && spec.series.length > 1 && <ChartLegend series={spec.series} at={shown} unit={spec.unit} />}
      {spec.source && <div className="text-[11px] text-dim text-right">{spec.source}</div>}
    </figure>
  );
}

type Axis = { xAt: (i: number) => number; yAt: (v: number) => number };

/** One part of a stacked area: filled between its band's bottom and top, with its top edge drawn as a line. */
function Area({ bands, xAt, yAt, colour }: Axis & { bands: (Band | null)[]; colour: string }) {
  const top: [number, number][] = [];
  const bottom: [number, number][] = [];
  bands.forEach((b, i) => {
    if (b === null) return;
    top.push([xAt(i), yAt(b.to)]);
    bottom.push([xAt(i), yAt(b.from)]);
  });
  if (!top.length) return null;
  const topEdge = smoothPath(top);
  const backAlongBottom = smoothPath(bottom.reverse()).replace(/^M/, "L");
  return (
    <g>
      <path d={`${topEdge} ${backAlongBottom} Z`} fill={colour} fillOpacity=".3" />
      <path d={topEdge} fill="none" stroke={colour} strokeWidth="2" strokeLinecap="round" />
    </g>
  );
}

/** A combo's line: a smooth line with a dot on each value, ringed so it stands out over the bars. */
function ComboLine({ data, xAt, yAt, colour }: Axis & { data: (number | null)[]; colour: string }) {
  const pts: [number, number][] = [];
  data.forEach((v, i) => {
    if (v !== null) pts.push([xAt(i), yAt(v)]);
  });
  if (!pts.length) return null;
  return (
    <g>
      <path d={smoothPath(pts)} fill="none" stroke={colour} strokeWidth="2.5" strokeLinecap="round" />
      {pts.map(([cx, cy], i) => <circle key={i} cx={cx} cy={cy} r="3.5" fill={colour} stroke="var(--t-surface-2)" strokeWidth="2" />)}
    </g>
  );
}

export function ChartPending() {
  return (
    <div className="glass rounded-[26px] p-4 my-2 flex flex-col gap-2" aria-label="Drawing chart">
      <div className="h-4 w-32 rounded bg-well" />
      <div className="h-7 w-24 rounded bg-well" />
      <div className="h-[110px] rounded-[14px] bg-well shimmer-bg" />
    </div>
  );
}
