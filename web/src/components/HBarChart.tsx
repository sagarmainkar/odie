// Horizontal bars: a row per x label, read top to bottom as a ranking. Asked for as hbar, or chosen for bars whose
// labels read better as rows (kindToDraw in chartData.ts).
import { Fragment, useRef, useState } from "react";
import { fmt, partColour, seriesName, type ChartSpec } from "./chartData";
import { ChartTip, type Tip } from "./ChartTip";
import { ChartLegend } from "./ChartLegend";
import { clearsOnLeave, pickKeys } from "./chartPick";

/**
 * hbar: label | bar | value on each row, the label wrapping so a long name still reads on a phone. One series of
 * positive values is drawn in one colour; with a negative value the bars grow either way from a zero line, gains
 * green and falls orange (a sector down 4% over the year). Several series: a thinner bar for each in its own colour,
 * named in a legend. Rows keep the model's order: it ranks them. Pointing at a row (or stepping with the arrow keys)
 * shows its hover card with every value in full.
 */
export function HBarChart({ spec }: { spec: ChartSpec }) {
  const [tip, setTip] = useState<Tip | null>(null);
  const [picked, setPicked] = useState<number | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const tracks = useRef<(HTMLDivElement | null)[]>([]);

  const values = spec.series.flatMap((s) => s.data.filter((v): v is number => v !== null));
  const lo = Math.min(0, ...values);
  const hi = Math.max(0, ...values);
  const span = hi - lo || 1;
  const zeroAt = (-lo / span) * 100;  // where zero sits along the track, in %
  const single = spec.series.length === 1;
  const signed = lo < 0;
  const unitOf = (k: number) => spec.series[k].unit ?? spec.unit;

  /** A bar's colour: green for a gain and orange for a fall when one series goes both ways, else its series's. */
  const colourOf = (k: number, v: number) => {
    if (!single || !signed) return partColour(k);
    if (v >= 0) return "var(--t-good)";
    return "var(--t-warn)";
  };

  /** Where a bar sits on its track, in %: from zero rightwards for a positive value, leftwards for a negative one; at
   *  least a sliver, so a tiny value still shows. */
  const barOf = (v: number) => {
    const width = Math.max((Math.abs(v) / span) * 100, 1.5);
    const left = v < 0 ? zeroAt - width : zeroAt;
    return { left, width };
  };

  /** Picks row i (or none) and points the hover card at the far end of its longest bar. */
  function pick(i: number | null) {
    setPicked(i);
    const track = i === null ? null : tracks.current[i];
    if (i === null || !track || !box.current) return setTip(null);
    const rows: Tip["rows"] = [];
    let end = zeroAt;
    spec.series.forEach((s, k) => {
      const v = s.data[i] ?? null;
      if (v === null) return;
      rows.push({ colour: colourOf(k, v), name: seriesName(spec.series, k), value: fmt(v, unitOf(k), { full: true }) });
      const { left, width } = barOf(v);
      end = Math.max(end, left + width);
    });
    const t = track.getBoundingClientRect();
    const b = box.current.getBoundingClientRect();
    setTip({ x: t.left - b.left + (t.width * end) / 100, y: t.top - b.top, title: String(spec.x[i]), rows });
  }

  const shade = (i: number) => (picked === null || picked === i ? 1 : 0.55);
  const rowEvents = (i: number) => ({ onPointerEnter: () => pick(i), onPointerDown: () => pick(i) });
  const trackHeight = single ? "h-3.5" : "h-3";
  return (
    <figure className="chart glass glass-solid rounded-[26px] px-4 pt-4 pb-3 my-2">
      <figcaption className="text-[13px] font-semibold text-muted truncate">{spec.title ?? spec.series[0].name ?? "Chart"}</figcaption>
      {!single && <ChartLegend series={spec.series} />}
      <div ref={box} className="relative mt-2.5 mb-1">
        <div className="chart-hbar-grid" role="img" aria-label={spec.title ?? "chart"}
          {...pickKeys(spec.x.length, picked, pick, true)} onPointerLeave={(e) => clearsOnLeave(e.pointerType) && pick(null)}>
          {spec.x.map((label, i) => (
            <Fragment key={i}>
              <div className="min-w-[64px] text-[13px] leading-[17px] text-ink-2" {...rowEvents(i)}>{label}</div>
              <div className="flex flex-col gap-1" ref={(el) => { tracks.current[i] = el; }} {...rowEvents(i)}>
                {spec.series.map((s, k) => {
                  const v = s.data[i] ?? null;
                  const bar = v === null ? null : barOf(v);
                  return (
                    <div key={k} className={`relative ${trackHeight}`}>
                      {signed && <div className="absolute -inset-y-1 w-px bg-line-2" style={{ left: `${zeroAt}%` }} />}
                      {v !== null && bar && (
                        <div className="chart-hbar-bar absolute inset-y-0 rounded-[3px]"
                          style={{ left: `${bar.left}%`, width: `${bar.width}%`, background: colourOf(k, v), opacity: shade(i) }} />
                      )}
                    </div>
                  );
                })}
              </div>
              <div className="flex flex-col gap-1" {...rowEvents(i)}>
                {spec.series.map((s, k) => {
                  const v = s.data[i] ?? null;
                  return <HBarValue key={k} value={v} unit={unitOf(k)} tone={single && signed} small={!single} />;
                })}
              </div>
            </Fragment>
          ))}
        </div>
        <ChartTip tip={tip} />
      </div>
      {spec.source && <div className="text-[11px] text-dim text-right">{spec.source}</div>}
    </figure>
  );
}

/** A row's value after its bar, shortened from 100,000 up (every digit in its title attribute); green or orange when
 *  the bars go both ways. */
function HBarValue({ value, unit, tone, small }: { value: number | null; unit?: string; tone: boolean; small: boolean }) {
  if (value === null) return <span className="text-right text-[12px] text-dim">–</span>;
  const text = fmt(value, unit);
  const full = fmt(value, unit, { full: true });
  let colour = "";
  if (tone) colour = value >= 0 ? "text-good" : "text-warn-ink";
  const size = small ? "text-[12px] leading-3" : "text-[13px] leading-[14px]";
  return <span className={`text-right font-semibold tabular-nums whitespace-nowrap ${size} ${colour}`} title={full !== text ? full : undefined}>{text}</span>;
}
