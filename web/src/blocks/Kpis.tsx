// Headline numbers: a kpis row of cards, or one stat card. A card holds its label, the big number (shortened from
// 100,000 up, every digit in its title), a change chip and, when given a trend, a small line of it.
import { partColour } from "../components/chartData";
import { InlineText } from "./InlineText";
import { kpiValue, sparkPath, SPARK_H, SPARK_W } from "./kpiValue";
import { formatChange, type KpiItem } from "./parse";
import { wideColumns } from "./wideColumns";

/** One card. `trendColour` colours its trend line; without one the line takes the first chart colour. */
export function KpiCard({ item, trendColour }: { item: KpiItem; trendColour?: string }) {
  const change = formatChange(item.change, item.change_unit);
  const isText = typeof item.value === "string";
  const shown = kpiValue(item);
  const full = kpiValue(item, { full: true });
  const valueSize = isText ? "text-[16px] leading-snug" : "text-[22px] leading-tight tabular-nums";
  return (
    <div className="glass glass-solid rounded-[20px] px-3.5 py-3 flex flex-col">
      <div className="text-[12px] font-semibold text-muted">{item.label}</div>
      <div className={`${valueSize} font-extrabold tracking-[-0.02em] mt-0.5 [overflow-wrap:anywhere]`} title={full !== shown ? full : undefined}>
        {isText ? <InlineText text={shown} /> : shown}
      </div>
      {change && <span className={`chip mt-1.5 self-start ${item.change! >= 0 ? "chip-good" : "chip-warn"}`}>{change}</span>}
      {item.trend && <Sparkline values={item.trend} colour={trendColour ?? partColour(0)} />}
    </div>
  );
}

// On a phone's two columns, an odd last card spans both, so three cards read 2 + 1 wide rather than leaving one alone.
const ODD_LAST_SPANS = "[&>:last-child:nth-child(odd)]:col-span-2 @xl:[&>:last-child:nth-child(odd)]:col-span-1";

/** A row of cards: two across on a phone (an odd last card spanning both), all in one row on a wide screen. When two
 *  or more have a trend, each line takes the chart colour of its card's place (the 1st card's blue, the 2nd's amber …),
 *  so a comparison's cards match its chart's lines, which come in the same order. A lone trend keeps the first colour. */
export function Kpis({ items }: { items: KpiItem[] }) {
  const several = items.filter((k) => k.trend).length >= 2;
  return (
    <div className={`grid grid-cols-2 ${wideColumns(items.length)} ${ODD_LAST_SPANS} gap-2 my-2`}>
      {items.map((k, i) => <KpiCard key={k.label} item={k} trendColour={several ? partColour(i) : undefined} />)}
    </div>
  );
}

/** A trend as a small line under the number: no axes, no labels, hidden from screen readers (the number says it). */
function Sparkline({ values, colour }: { values: number[]; colour: string }) {
  return (
    <svg className="kpi-spark" viewBox={`0 0 ${SPARK_W} ${SPARK_H}`} preserveAspectRatio="none" aria-hidden="true">
      <path d={sparkPath(values)} style={{ stroke: colour }} />
    </svg>
  );
}
