import { fmt, partColour, type ChartSeries } from "./chartData";

/** The names of a chart's series under it, each beside its colour; a series on a combo's right scale says so. With
 *  `at` (stacked bars and areas), each name has its value at that x label after it, in the chart's unit. */
export function ChartLegend({ series, at, unit }: { series: ChartSeries[]; at?: number; unit?: string }) {
  return (
    <div className="flex flex-wrap gap-x-3 gap-y-1 mt-1.5 text-[12px] leading-4 text-muted">
      {series.map((s, k) => {
        const value = at === undefined ? null : s.data[at] ?? null;
        return (
          <span key={k} className="inline-flex items-center gap-1.5">
            <i className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: partColour(k) }} />
            {s.name ?? `Series ${k + 1}`}
            {value !== null && <span className="text-ink-2 tabular-nums">{fmt(value, s.unit ?? unit)}</span>}
            {s.right && <span className="text-dim">(right scale)</span>}
          </span>
        );
      })}
    </div>
  );
}
