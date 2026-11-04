// The hover card every chart shares (styles.css, .chart-tip): a small card beside the pointer with the label, each
// series's colour, name and full value, and an optional note ("40% of total", "▲ 4.2% since start").
import { useLayoutEffect, useRef, useState } from "react";
import { tipPlace } from "./chartGeometry";

export type TipRow = { colour: string; name: string; value: string };

/** What the card shows and where it points: x and y in px from the top left of the card's positioned parent. */
export type Tip = { x: number; y: number; title: string; rows: TipRow[]; note?: string };

/** The card, inside a parent with position: relative. With tip null it fades out still showing what it last did, so
 *  it doesn't empty mid-fade; it is always in the page, so screen readers hear each new point as it changes. */
export function ChartTip({ tip }: { tip: Tip | null }) {
  const card = useRef<HTMLDivElement>(null);
  const [kept, setKept] = useState(tip);
  if (tip && tip !== kept) setKept(tip);  // remember the last tip shown (React's "state from props" pattern)
  const shown = tip ?? kept;

  useLayoutEffect(() => {
    const el = card.current;
    if (!el || !tip) return;
    const box = el.offsetParent as HTMLElement | null;
    const boxWidth = box?.clientWidth ?? 0;
    const boxHeight = box?.clientHeight ?? Infinity;
    const { left, top } = tipPlace(tip.x, tip.y, el.offsetWidth, el.offsetHeight, boxWidth, boxHeight);
    el.style.left = `${left}px`;
    el.style.top = `${top}px`;
  }, [tip]);

  return (
    <div ref={card} className={`chart-tip${tip ? " chart-tip-on" : ""}`} role="status" aria-live="polite">
      {shown && (
        <>
          <div className="chart-tip-title">{shown.title}</div>
          {shown.rows.map((row, k) => (
            <div key={k} className="chart-tip-row">
              <i style={{ background: row.colour }} />
              <span className="chart-tip-name">{row.name}</span>
              <b className="chart-tip-value">{row.value}</b>
            </div>
          ))}
          {shown.note && <div className="chart-tip-note">{shown.note}</div>}
        </>
      )}
    </div>
  );
}
