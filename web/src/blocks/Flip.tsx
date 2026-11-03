import { useState, type CSSProperties } from "react";
import { flipColumns } from "./flipColumns";
import { InlineText } from "./InlineText";
import type { FlipCard } from "./parse";

/** Flash cards in a grid: every card shows its question; a tap turns that card over to the answer, with its photo
 *  when there is one. Each card turns on its own, and back on another tap. The grid has flipColumns columns on a wide
 *  screen and two on a phone (an odd last card spans both), so no card sits alone on the last row. A card grows with
 *  its text (both faces share one grid cell, so the longer side sets the height), and words are never cut. The turn
 *  is CSS (styles.css, .flip-*); with reduced motion the answer fades in instead. */
export function Flip({ title, cards }: { title?: string; cards: FlipCard[] }) {
  const [turned, setTurned] = useState<boolean[]>(() => cards.map(() => false));
  const toggle = (i: number) => setTurned((was) => was.map((t, k) => (k === i ? !t : t)));
  const withPhoto = cards.some((c) => c.image);  // one photo makes every card taller, so the rows stay even
  const grid = withPhoto ? "flip-grid flip-tall" : "flip-grid";
  return (
    <div className="my-2">
      {title && <b className="block text-[17px] font-bold tracking-[-0.01em] mb-2">{title}</b>}
      <div className={grid} style={{ "--flip-cols": flipColumns(cards.length) } as CSSProperties}>
        {cards.map((c, i) => (
          <button key={i} type="button" onClick={() => toggle(i)} aria-pressed={turned[i] === true}
            aria-label={turned[i] ? `${c.front}: ${c.back}` : `${c.front}, tap to see the answer`} className="flip-scene text-left">
            <span className={`flip-inner ${turned[i] ? "is-turned" : ""}`}>
              <span className="flip-face flip-front glass glass-solid rounded-[20px] px-3.5 py-3">
                <span className="text-[11px] font-semibold tracking-[.06em] uppercase text-muted tabular-nums">{i + 1} / {cards.length}</span>
                <span className="flex-1 flex items-center text-[15px] leading-[21px] font-semibold"><InlineText text={c.front} /></span>
                <span className="text-[11.5px] text-muted">Tap to flip</span>
              </span>
              <span className="flip-face flip-back rounded-[20px] overflow-hidden text-white" style={{ background: "var(--t-iris)" }}>
                {c.image && <img src={c.image} alt="" loading="lazy" referrerPolicy="no-referrer" className="w-full h-[88px] object-cover shrink-0" />}
                <span className="flex-1 flex items-center px-3.5 py-3 text-[14.5px] leading-[20px] font-semibold"><InlineText text={c.back} /></span>
              </span>
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
