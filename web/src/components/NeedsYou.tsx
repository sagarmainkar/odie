import { AnimatePresence, motion } from "framer-motion";
import { useState } from "react";
import { badgeTone, tileColour, type Need, type NeedAction, type WatchNote } from "../needs";
import { mediaUrl } from "../media";
import { Orb } from "./Orb";
import { Icon, Tile } from "./Tile";
import { WatchClosed, type WatchClosedItem } from "./WatchClosed";

const ask = (q: string) => { location.hash = `#chat?q=${encodeURIComponent(q)}`; };

/** Today's "Needs you": one card per thing to act on, from the watch's last check and the user's own reminders. Each
 * card has its two buttons. What the watch did fold into one "done while you were away" line: its notes (with any
 * files) and the reminders it closed (with Reopen). open: start unfolded (tests). */
export function NeedsYou({ items, footer, closed, notes = [], onAct, onReopen, open = false }: {
  items: Need[] | null; footer: string; closed: WatchClosedItem[]; notes?: WatchNote[];
  onAct: (need: Need, act: NeedAction) => void; onReopen: (id: number) => void; open?: boolean;
}) {
  const [showClosed, setShowClosed] = useState(open);
  const doneCount = closed.length + notes.length;
  return (
    <section className="flex flex-col gap-2.5" aria-label="Needs you">
      <div className="flex items-baseline gap-2 px-1">
        <div className="text-[21px] font-bold tracking-[-0.015em] flex-1">Needs you</div>
        {footer && <div className="text-[12px] text-dim truncate max-w-[65%]">{footer}</div>}
      </div>
      {items !== null && items.length === 0 && (
        <div className="glass rounded-[26px] flex flex-col items-center text-center pt-6 pb-5">
          <Orb size={56} halo />
          <span className="serif text-[24px] mt-2">All clear.</span>
          <div className="text-[13.5px] text-muted">I check your mail every 30 minutes and tell you when something needs you.</div>
        </div>
      )}
      <AnimatePresence initial={false}>
        {(items ?? []).map((n) => (
          <motion.div key={n.ref} layout initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, scale: 0.97 }}
            transition={{ duration: 0.2 }} className="glass glass-solid rounded-[24px] px-4 py-3.5 flex flex-col gap-3">
            <button type="button" onClick={() => ask(n.ask)} className="flex items-start gap-3 text-left">
              <Tile icon={n.icon} color={tileColour(n.icon)} />
              <span className="flex-1 min-w-0">
                <span className="block text-[15.5px] leading-[21px] font-semibold break-words">{n.title}</span>
                {n.why && <span className="block text-[13px] leading-[18px] text-muted mt-0.5 line-clamp-2">{n.why}</span>}
                {n.badge && <span className={`chip ${badgeTone(n.badge) === "warn" ? "chip-warn" : "chip-soft"} mt-1.5 inline-flex`}>{n.badge}</span>}
              </span>
            </button>
            <div className="flex gap-2 pl-12">
              <button type="button" onClick={() => onAct(n, n.main)} className="pill pill-solid h-9 px-4 text-[13.5px] shadow-none">{n.main.label}</button>
              <button type="button" onClick={() => onAct(n, n.other)} className="pill h-9 px-4 text-[13.5px]">{n.other.label}</button>
            </div>
          </motion.div>
        ))}
      </AnimatePresence>
      {doneCount > 0 && (
        <div className="glass rounded-[22px] px-3 py-1">
          <button type="button" onClick={() => setShowClosed(!showClosed)} aria-expanded={showClosed}
            className="w-full flex items-center gap-2 py-2 text-left text-[13.5px] text-good font-semibold">
            <span className="flex-1">✓ {doneCount} done while you were away</span>
            <span className="text-dim" aria-hidden="true">{showClosed ? "‹" : "›"}</span>
          </button>
          {showClosed && notes.map((n) => (
            <div key={n.at + n.message} className="flex items-start gap-3 py-2.5 px-1 border-t border-line">
              <span className="w-9 h-9 shrink-0 rounded-full grid place-items-center bg-good text-white" aria-hidden="true">
                <Icon name="check" size={18} stroke={2.6} />
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-[14px] leading-[1.35] text-ink-2 break-words">{n.message}</div>
                {n.media.map((m) => (
                  <a key={m.id} href={mediaUrl(m)} download={m.filename} className="pill h-8 px-3 text-[12.5px] mt-1.5 inline-flex">{m.filename || m.title}</a>
                ))}
              </div>
            </div>
          ))}
          {showClosed && <WatchClosed items={closed} onReopen={onReopen} />}
        </div>
      )}
    </section>
  );
}
