import { Fragment, useState } from "react";
import { cellColour, cellText, rangeOf } from "./heatmapColour";
import type { HeatScale } from "./parse";

const SHOW_NUMBERS_UP_TO = 6;  // columns; past that the cells are too narrow on a phone, so a tap shows the number

/** A grid of shaded cells, column labels across the top and row labels down the side. With six columns or fewer each
 *  cell prints its number; with more, a tap on a cell shows "row · col: value" under the grid. */
export function Heatmap({ title, rows, cols, values, unit, scale }: {
  title?: string; rows: string[]; cols: string[]; values: (number | null)[][]; unit?: string; scale: HeatScale;
}) {
  const [picked, setPicked] = useState<{ row: number; col: number } | null>(null);
  const range = rangeOf(values);
  const numbersInCells = cols.length <= SHOW_NUMBERS_UP_TO;
  const cell = "h-8 rounded-[8px] grid place-items-center text-[11.5px] leading-none font-semibold tabular-nums text-ink";
  return (
    <div className="glass glass-solid rounded-[24px] px-4 py-3.5 my-2">
      {title && <b className="block text-[17px] font-bold tracking-[-0.01em] mb-2">{title}</b>}
      <div className="grid gap-1" style={{ gridTemplateColumns: `minmax(0, max-content) repeat(${cols.length}, minmax(0, 1fr))` }} role="table" aria-label={title ?? "Heat map"}>
        <span />
        {cols.map((c, j) => <span key={j} className="text-[11px] font-semibold text-muted text-center truncate" role="columnheader">{c}</span>)}
        {rows.map((r, i) => (
          <Fragment key={i}>
            <span className="text-[12px] font-semibold truncate pr-1.5 self-center max-w-[96px]" role="rowheader">{r}</span>
            {cols.map((c, j) => {
              const v = values[i][j];
              return (
                <button key={j} type="button" onClick={() => setPicked({ row: i, col: j })} aria-label={`${r}, ${c}: ${cellText(v, unit)}`}
                  className={cell} style={{ background: cellColour(v, range, scale) }}>
                  {numbersInCells && v !== null ? cellText(v, unit) : ""}
                </button>
              );
            })}
          </Fragment>
        ))}
      </div>
      {picked && (
        <div className="text-[12.5px] text-muted mt-2 tabular-nums">
          {rows[picked.row]} · {cols[picked.col]}: <span className="font-semibold text-ink">{cellText(values[picked.row][picked.col], unit)}</span>
        </div>
      )}
    </div>
  );
}
