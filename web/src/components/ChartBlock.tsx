// Charts that go up and down (line, bar, area, stacked, combo), and the parser every chart goes through. Pies and
// donuts, and horizontal bars, have files of their own. Hand-drawn SVG at the width the chart has on screen: the sums
// behind it are in chartData.ts, where things go in chartLayout.ts, the marks in *Marks.tsx, the hover card in
// ChartTip.tsx.
import { useId, useMemo, useRef, useState, type PointerEvent } from "react";
import {
  changePct, chartKind, chartScales, fmt, isOnRightScale, kindToDraw, maxSeries, pieSlices, stackSeries, totalAt,
  type ChartKind, type ChartSeries, type ChartSpec,
} from "./chartData";
import { namesFitAtEnds, seriesEnds, xyLayout, xyTip, type XYLayout } from "./chartLayout";
import { pickKeys } from "./chartPick";
import { useWidth } from "./useWidth";
import { ChartTip } from "./ChartTip";
import { ChartLegend } from "./ChartLegend";
import { LineMarks, Crosshair } from "./LineMarks";
import { BarMarks, ComboMarks, StackMarks } from "./ColumnMarks";
import { AreaMarks } from "./AreaMarks";
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
 *                                                               {"name": "Margin", "unit": "%", "data": [18.4, 16]}]}
 *  figure: false (a % change comparison, where a change of a change means nothing) drops the headline number and the
 *  change chip; only true or false count. tone: "change" (exactly that) colours a one-series line by direction from its
 *  first value. Anything else in either is ignored, so an older or sloppier answer still draws.
 *    {..., "figure": false} → spec.figure false;  {..., "figure": "false"} → no figure (shown);  {..., "tone": "Change"} → no tone */
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
  const spec: ChartSpec = { type, title: typeof d.title === "string" ? d.title : undefined, x,
    series, unit, source: typeof d.source === "string" ? d.source : undefined };
  if (typeof d.figure === "boolean") spec.figure = d.figure;
  if (d.tone === "change") spec.tone = "change";
  return spec;
}

/** One series as the model wrote it → its name, its numbers (anything else a gap), its own unit, its scale. */
function readSeries(s: any, k: number, type: ChartKind, chartUnit: string | undefined): ChartSeries {
  const name = typeof s.name === "string" ? s.name : undefined;
  const data = s.data.map((v: any) => (typeof v === "number" && isFinite(v) ? v : null));
  const unit = typeof s.unit === "string" ? s.unit : undefined;
  const right = isOnRightScale(type, k, unit, s.axis, chartUnit);
  return { name, data, unit, right };
}

const WIDE_FROM = 60;  // a line with this many points may be drawn wider than the usual cap

/** A chart of any kind: pies and donuts, and horizontal bars (asked for, or bars that read better as rows: see
 *  kindToDraw), have drawings of their own; the rest go up and down. */
export function ChartBlock({ spec }: { spec: ChartSpec }) {
  if (spec.type === "pie" || spec.type === "donut") return <PieChart spec={spec} />;
  if (kindToDraw(spec) === "hbar") return <HBarChart spec={spec} />;
  return <XYChart spec={spec} />;
}

/** Line, bar, area, stacked and combo: x labels along the bottom, values up the side, a hover card per x label. */
function XYChart({ spec }: { spec: ChartSpec }) {
  const plot = useRef<HTMLDivElement>(null);
  const svg = useRef<SVGSVGElement>(null);
  const width = useWidth(plot);
  const [hover, setHover] = useState<number | null>(null);
  const gid = useId().replace(/[^a-zA-Z0-9]/g, "");
  const n = spec.x.length;
  const piled = spec.type === "stacked" || spec.type === "area";  // the series pile on each other
  const bands = useMemo(() => (piled ? stackSeries(spec.series, n) : null), [spec, n, piled]);
  const scales = useMemo(() => chartScales(spec, bands), [spec, bands]);
  const layout = useMemo(() => xyLayout(spec, width, scales), [spec, width, scales]);
  const tip = useMemo(() => (hover === null ? null : xyTip(spec, hover, layout)), [spec, hover, layout]);

  /** Picks the x label nearest the pointer. */
  function pickAt(e: PointerEvent) {
    const r = svg.current?.getBoundingClientRect();
    if (!r || !r.width) return;
    const x = ((e.clientX - r.left) / r.width) * layout.W;
    let best = 0;
    for (let i = 1; i < n; i++) if (Math.abs(layout.xAt(i) - x) < Math.abs(layout.xAt(best) - x)) best = i;
    setHover(best);
  }

  const severalLines = spec.type === "line" && spec.series.length > 1;
  const namedAtEnds = namesFitAtEnds(spec, width);
  const legend = spec.type === "combo" || (spec.type === "bar" && spec.series.length > 1) || (severalLines && !namedAtEnds);
  const wide = spec.type === "line" && n >= WIDE_FROM;
  return (
    <figure className={`chart${wide ? " chart-wide" : ""} glass glass-solid rounded-[26px] px-4 pt-4 pb-3 my-2`}>
      <Headline spec={spec} hover={hover} />
      <div ref={plot} className="relative mt-2">
        <svg ref={svg} width="100%" height={layout.H} viewBox={`0 0 ${layout.W} ${layout.H}`} className="chart-svg"
          role="img" aria-label={spec.title ?? "chart"} {...pickKeys(n, hover, setHover)}
          onPointerDown={pickAt} onPointerMove={(e) => (e.buttons || e.pointerType === "mouse") && pickAt(e)}
          onPointerLeave={() => setHover(null)}>
          <XLabels spec={spec} layout={layout} />
          {spec.type === "line" && <LineMarks spec={spec} layout={layout} gid={gid} hover={hover} />}
          {spec.type === "bar" && <BarMarks spec={spec} layout={layout} hover={hover} />}
          {spec.type === "stacked" && bands && <StackMarks bands={bands} layout={layout} hover={hover} />}
          {spec.type === "area" && bands && <AreaMarks bands={bands} layout={layout} />}
          {spec.type === "combo" && <ComboMarks spec={spec} layout={layout} hover={hover} />}
          {(spec.type === "area" || spec.type === "combo") && hover !== null && <Crosshair layout={layout} at={hover} />}
        </svg>
        <ChartTip tip={tip} />
      </div>
      {legend && <ChartLegend series={spec.series} />}
      {piled && spec.series.length > 1 && <ChartLegend series={spec.series} at={hover ?? lastIndex(spec)} unit={spec.unit} />}
      {spec.source && <div className="text-[11px] text-dim text-right">{spec.source}</div>}
    </figure>
  );
}

/** The index of the first series's last value (gaps skipped): where the headline number is read when nothing is
 *  picked. */
function lastIndex(spec: ChartSpec): number {
  const { last } = seriesEnds(spec.series[0].data);
  if (last < 0) return spec.x.length - 1;
  return last;
}

/** The title, the line's change chip, and the big number: the value at the picked x label, or the latest. A stacked
 *  chart's number is the whole pile; the other series's values sit beside it. figure: false keeps only the title. The
 *  big number is shortened from 100,000 up; its title attribute has every digit. */
function Headline({ spec, hover }: { spec: ChartSpec; hover: number | null }) {
  const piled = spec.type === "stacked" || spec.type === "area";
  const pct = spec.type === "line" ? changePct(spec.series[0].data) : null;
  const shown = hover ?? lastIndex(spec);
  const big = piled ? totalAt(spec.series, shown) : spec.series[0].data[shown] ?? null;
  const bigUnit = piled ? spec.unit : spec.series[0].unit ?? spec.unit;
  const listed = piled ? [] : spec.series.slice(1);  // a pile's parts have their values in the legend
  const withFigure = spec.figure !== false;
  const bigText = big === null ? "–" : fmt(big, bigUnit);
  const bigFull = big === null ? "–" : fmt(big, bigUnit, { full: true });
  return (
    <>
      <figcaption className="flex items-center justify-between gap-2">
        <span className="text-[13px] font-semibold text-muted truncate">{spec.title ?? spec.series[0].name ?? "Chart"}</span>
        {pct !== null && withFigure && <span className={`chip ${pct >= 0 ? "chip-good" : "chip-warn"}`}>{pct >= 0 ? "▲" : "▼"} {Math.abs(pct).toFixed(1)}%</span>}
      </figcaption>
      {withFigure && (
        <div className="flex items-baseline gap-2 mt-0.5 min-w-0">
          <span className="text-[30px] leading-tight font-extrabold tracking-[-0.03em] tabular-nums" title={bigFull !== bigText ? bigFull : undefined}>{bigText}</span>
          <span className="text-[12px] text-muted tabular-nums truncate">
            {hover !== null ? spec.x[shown] : ""}
            {listed.map((s, k) => {
              const v = s.data[shown] ?? null;
              if (v === null) return null;
              return <span key={k} className="ml-2">{s.name ? `${s.name} ` : ""}{fmt(v, s.unit ?? spec.unit)}</span>;
            })}
          </span>
        </div>
      )}
    </>
  );
}

/** The x labels that fit along the bottom (layout.xLabels): under each column, or for a line the first one starting
 *  at the left edge, the last ending at the right and the rest centred. */
function XLabels({ spec, layout }: { spec: ChartSpec; layout: XYLayout }) {
  const last = spec.x.length - 1;
  const anchor = (i: number) => {
    if (layout.slotted || last === 0) return "middle";
    if (i === 0) return "start";
    if (i === last) return "end";
    return "middle";
  };
  return (
    <g>
      {layout.xLabels.map((i) => (
        <text key={i} x={layout.xAt(i)} y={layout.H - 7} textAnchor={anchor(i)} className="chart-axis">{String(spec.x[i])}</text>
      ))}
    </g>
  );
}

/** The grey card a chart (or a diagram) shows while its fence is still streaming in. */
export function ChartPending() {
  return (
    <div className="glass rounded-[26px] p-4 my-2 flex flex-col gap-2" aria-label="Drawing chart">
      <div className="h-4 w-32 rounded bg-well" />
      <div className="h-7 w-24 rounded bg-well" />
      <div className="h-[110px] rounded-[14px] bg-well shimmer-bg" />
    </div>
  );
}
