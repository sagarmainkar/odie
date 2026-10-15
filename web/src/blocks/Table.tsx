import { useContext, useState } from "react";
import { InCard } from "./InCard";
import { InlineText } from "./InlineText";
import type { Highlight } from "./parse";
import { isNumberColumn, nextSort, sortedOrder, type SortState } from "./tableSort";

type Props = { columns: string[]; rows: string[][]; highlight?: Highlight; caption?: string };

/** Options compared side by side. Tap a header to sort (up, down, back); the highlighted row or column is tinted
 *  and badged "Best"; a wide table scrolls sideways inside its card, never the page. */
export function Table({ columns, rows, highlight, caption }: Props) {
  const inCard = useContext(InCard);
  const [sort, setSort] = useState<SortState>(null);
  const order = sortedOrder(rows, sort);
  const bestRow = highlight && "row" in highlight ? highlight.row : -1;
  const bestColumn = highlight && "column" in highlight ? highlight.column : -1;
  const numeric = columns.map((_, c) => isNumberColumn(rows, c));
  const frame = inCard ? "my-2" : "glass glass-solid rounded-[20px] my-2 overflow-hidden";

  return (
    <div className={frame}>
      {caption && <div className={`${inCard ? "" : "px-4"} pt-3 text-[13px] font-bold text-muted`}><InlineText text={caption} /></div>}
      <div className="overflow-x-auto overscroll-x-contain [-webkit-overflow-scrolling:touch]">
        <table className="min-w-full border-collapse text-[14px] leading-[20px] [overflow-wrap:normal]">
          <thead>
            <tr>
              {columns.map((name, c) => (
                <th key={c} aria-sort={ariaSort(sort, c)} className={`p-0 border-b border-line ${c === bestColumn ? "bg-ember-tint" : ""}`}>
                  <button type="button" onClick={() => setSort(nextSort(sort, c))}
                    className={`w-full flex items-center gap-1 py-2.5 ${cellPadding(c, columns.length, inCard)} text-[12px] font-bold text-muted whitespace-nowrap ${numeric[c] ? "justify-end" : ""}`}>
                    <span>{name}</span>
                    <SortArrow sort={sort} column={c} />
                    {c === bestColumn && <span className="chip chip-inline chip-good">Best</span>}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="[&>tr:last-child>td]:border-b-0">
            {order.map((r) => (
              <tr key={r} className={r === bestRow ? "bg-ember-tint" : ""}>
                {rows[r].map((cell, c) => (
                  <td key={c} className={cellClass(cell, c, columns.length, inCard, numeric[c], c === bestColumn)}>
                    <InlineText text={cell} />
                    {c === 0 && r === bestRow && <> <span className="chip chip-inline chip-good">Best</span></>}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SortArrow({ sort, column }: { sort: SortState; column: number }) {
  if (!sort || sort.column !== column) return null;
  return <span className="text-ink-2">{sort.direction === "up" ? "▲" : "▼"}</span>;
}

function ariaSort(sort: SortState, column: number): "ascending" | "descending" | undefined {
  if (!sort || sort.column !== column) return undefined;
  return sort.direction === "up" ? "ascending" : "descending";
}

/** Edge cells line up with the card's padding; inside a section the card already pads, so they sit flush. */
function cellPadding(column: number, count: number, inCard: boolean): string {
  if (column === 0) return inCard ? "pl-0 pr-3" : "pl-4 pr-3";
  if (column === count - 1) return inCard ? "pl-3 pr-0" : "pl-3 pr-4";
  return "px-3";
}

function cellClass(cell: string, column: number, count: number, inCard: boolean, numeric: boolean, best: boolean): string {
  const parts = ["py-2.5 border-b border-line align-top", cellPadding(column, count, inCard)];
  // Short cells stay on one line (the table scrolls sideways instead); long ones wrap in a column of sensible width.
  if (cell.length > 28) parts.push("min-w-[180px] whitespace-normal");
  else parts.push("whitespace-nowrap");
  if (column === 0) parts.push("font-semibold");
  if (numeric) parts.push("text-right tabular-nums");
  if (best) parts.push("bg-ember-tint");
  return parts.join(" ");
}
