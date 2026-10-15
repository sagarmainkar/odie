import { Fragment } from "react";
import { fmt, partColour, type ChartSpec } from "./chartData";
import { ChartLegend } from "./ChartLegend";

/** hbar: a row per x label, its name on the left (wrapping, so a long name still reads on a phone) and a bar for each
 *  series to its right, with the value after it. Rows keep the model's order: it ranks them. A negative value grows
 *  left from a zero line, so a fall reads as one (a sector down 4% over the year). */
export function HBarChart({ spec }: { spec: ChartSpec }) {
  const values = spec.series.flatMap((s) => s.data.filter((v): v is number => v !== null));
  const lo = Math.min(0, ...values);
  const hi = Math.max(0, ...values);
  const span = hi - lo || 1;
  const zeroAt = (-lo / span) * 100;  // where zero sits along the track, in %

  return (
    <figure className="chart glass glass-solid rounded-[26px] px-4 pt-4 pb-3 my-2">
      <figcaption className="text-[13px] font-semibold text-muted truncate">{spec.title ?? spec.series[0].name ?? "Chart"}</figcaption>
      {spec.series.length > 1 && <ChartLegend series={spec.series} />}
      <div className="mt-2.5 mb-1 grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] gap-x-3 gap-y-2.5 items-center">
        {spec.x.map((label, i) => (
          <Fragment key={i}>
            <div className="text-[13px] leading-[17px] text-ink-2 break-words">{label}</div>
            <div className="flex flex-col gap-1">
              {spec.series.map((s, k) => {
                const v = s.data[i] ?? null;
                return (
                  <div key={k} className="flex items-center gap-2">
                    <div className="relative h-2.5 flex-1 rounded-full bg-well">
                      {lo < 0 && <div className="absolute -inset-y-1 w-px bg-line-2" style={{ left: `${zeroAt}%` }} />}
                      {v !== null && <HBar value={v} span={span} zeroAt={zeroAt} colour={partColour(k)} />}
                    </div>
                    <span className="min-w-[52px] text-right text-[12px] tabular-nums text-muted whitespace-nowrap">{v === null ? "–" : fmt(v, s.unit ?? spec.unit)}</span>
                  </div>
                );
              })}
            </div>
          </Fragment>
        ))}
      </div>
      {spec.source && <div className="text-[11px] text-dim text-right">{spec.source}</div>}
    </figure>
  );
}

/** One bar on its track: from zero rightwards for a positive value, leftwards for a negative one; at least a sliver,
 *  so a tiny value still shows. */
function HBar({ value, span, zeroAt, colour }: { value: number; span: number; zeroAt: number; colour: string }) {
  const width = Math.max((Math.abs(value) / span) * 100, 1.5);
  const left = value < 0 ? zeroAt - width : zeroAt;
  return <div className="absolute inset-y-0 rounded-full" style={{ left: `${left}%`, width: `${width}%`, background: colour }} />;
}
