import { AnimatePresence, motion } from "framer-motion";
import { useState } from "react";
import { badgeTone, buttonsOf, tileColour, type Need, type NeedAction, type WatchNote } from "../needs";
import { mediaUrl } from "../media";
import { Orb } from "./Orb";
import { Icon, Tile } from "./Tile";
import { WatchClosed, type WatchClosedItem } from "./WatchClosed";

const ask = (q: string) => { location.hash = `#chat?q=${encodeURIComponent(q)}`; };

/** A Pulse's "Needs you": one card per thing to act on, from the watch's last check and the user's own reminders. Each
 * card has the same three buttons: its move, Done and Later. What the watch did fold into one "done today" line: its
 * notes (with any files) and what it closed (with Reopen). open: start unfolded (tests). */
export function NeedsYou({ items, footer, closed, notes = [], onAct, onReopen, open = false }: {
  items: Need[] | null; footer: string; closed: WatchClosedItem[]; notes?: WatchNote[];
  onAct: (need: Need, act: NeedAction) => void; onReopen: (id: number) => void; open?: boolean;
}) {
  const [showClosed, setShowClosed] = useState(open);
  const doneCount = closed.length + notes.length;
  return (
    <section className="flex flex-col gap-2.5" aria-label="Needs you">
      <div className="flex items-baseline gap-2 px-1">
        <div className="text-heading font-bold tracking-[-0.015em] flex-1">Needs you</div>
        {footer && <div className="text-caption text-dim truncate max-w-[65%]">{footer}</div>}
      </div>
      {items !== null && items.length === 0 && (
        <div className="glass rounded-card flex flex-col items-center text-center pt-6 pb-5">
          <Orb size={56} halo />
          <span className="serif text-display-sm mt-2">All clear.</span>
          <div className="text-ui text-muted">I check your mail every 30 minutes and tell you when something needs you.</div>
        </div>
      )}
      <AnimatePresence initial={false}>
        {(items ?? []).map((n) => (
          <motion.div key={n.ref} layout initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, scale: 0.97 }}
            transition={{ duration: 0.2 }} className="glass glass-solid rounded-card px-4 py-3.5 flex flex-col gap-3">
            <button type="button" onClick={() => ask(n.ask)} className="flex items-start gap-3 text-left">
              <Tile icon={n.icon} color={tileColour(n.icon)} />
              <span className="flex-1 min-w-0">
                <span className="block text-body leading-[21px] font-semibold break-words">{n.title}</span>
                {n.why && <span className="block text-small leading-[18px] text-muted mt-0.5 line-clamp-2">{n.why}</span>}
                {n.badge && <span className={`chip ${badgeTone(n.badge) === "warn" ? "chip-warn" : "chip-soft"} mt-1.5 inline-flex`}>{n.badge}</span>}
              </span>
            </button>
            {/* The move first and solid, then Done and Later; on a phone a long move takes its own line. */}
            <div className="flex flex-wrap gap-2 pl-12">
              {buttonsOf(n).map((a, i) => (
                <button key={a.action + i} type="button" onClick={() => onAct(n, a)}
                  className={i === 0 ? "pill pill-solid h-9 px-4 text-ui shadow-none max-w-full truncate" : "pill h-9 px-3.5 text-ui"}>{a.label}</button>
              ))}
            </div>
          </motion.div>
        ))}
      </AnimatePresence>
      {doneCount > 0 && (
        <div className="glass rounded-tile px-3 py-1">
          <button type="button" onClick={() => setShowClosed(!showClosed)} aria-expanded={showClosed}
            className="w-full flex items-center gap-2 py-2 text-left text-ui text-good font-semibold">
            <span className="flex-1">✓ {doneCount} done today</span>
            <span className="text-dim" aria-hidden="true">{showClosed ? "‹" : "›"}</span>
          </button>
          {showClosed && notes.map((n) => (
            <div key={n.at + n.message} className="flex items-start gap-3 py-2.5 px-1 border-t border-line">
              <span className="w-9 h-9 shrink-0 rounded-full grid place-items-center bg-good text-white" aria-hidden="true">
                <Icon name="check" size={18} stroke={2.6} />
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-ui leading-[1.35] text-ink-2 break-words">{n.message}</div>
                {n.media.map((m) => (
                  <a key={m.id} href={mediaUrl(m)} download={m.filename} className="pill h-8 px-3 text-small mt-1.5 inline-flex">{m.filename || m.title}</a>
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
