import { useState } from "react";
import { InlineText } from "./InlineText";
import type { FlipCard } from "./parse";

/** Flash cards in a strip: the front shows the question; a tap turns the card over to the answer, with its photo when
 *  there is one. Each card turns on its own, and turns back on another tap. The turn is CSS (styles.css, .flip-*);
 *  with reduced motion the back fades in instead. */
export function Flip({ title, cards }: { title?: string; cards: FlipCard[] }) {
  const [turned, setTurned] = useState<boolean[]>(() => cards.map(() => false));
  const toggle = (i: number) => setTurned((was) => was.map((t, k) => (k === i ? !t : t)));
  return (
    <div className="my-2">
      {title && <b className="block text-[17px] font-bold tracking-[-0.01em] mb-2">{title}</b>}
      <div className="flex gap-2.5 overflow-x-auto no-scrollbar -mx-1 px-1 py-1">
        {cards.map((c, i) => (
          <button key={i} type="button" onClick={() => toggle(i)} aria-pressed={turned[i] === true} aria-label={turned[i] ? `${c.front}: ${c.back}` : `${c.front}, tap to see the answer`}
            className="flip-scene shrink-0 w-[156px] h-[176px] text-left">
            <span className={`flip-inner ${turned[i] ? "is-turned" : ""}`}>
              <span className="flip-face flip-front glass glass-solid rounded-[20px] px-3.5 py-3 flex flex-col">
                <span className="text-[11px] font-semibold tracking-[.06em] uppercase text-muted tabular-nums">{i + 1} / {cards.length}</span>
                <span className="flex-1 grid place-items-center text-center text-[15.5px] leading-[21px] font-semibold"><InlineText text={c.front} /></span>
                <span className="text-[11.5px] text-muted text-center">Tap to flip</span>
              </span>
              <span className="flip-face flip-back rounded-[20px] overflow-hidden flex flex-col text-white" style={{ background: "var(--t-iris)" }}>
                {c.image && <img src={c.image} alt="" loading="lazy" referrerPolicy="no-referrer" className="w-full h-[88px] object-cover" />}
                <span className={`flex-1 grid place-items-center text-center px-3.5 ${c.image ? "py-2 text-[14px] leading-[19px]" : "py-3 text-[15.5px] leading-[21px]"} font-semibold`}>
                  <InlineText text={c.back} />
                </span>
              </span>
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
