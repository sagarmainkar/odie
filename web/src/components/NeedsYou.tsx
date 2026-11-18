import { AnimatePresence, motion } from "framer-motion";
import { useState } from "react";
import { badgeTone, buttonsOf, tileColour, type Need, type NeedAction, type WatchNote } from "../needs";
import { mediaUrl } from "../media";
import { Orb } from "./Orb";
import { Icon, Tile } from "./Tile";
import { WatchClosed, type WatchClosedItem } from "./WatchClosed";
import type { JobDone, LoopDone } from "../pulse";

const ask = (q: string) => { location.hash = `#chat?q=${encodeURIComponent(q)}`; };

/** A Pulse's "Needs you": one card per thing to act on, from the watch's last check, Odie's loops and jobs, and the
 * user's own reminders. Each card has its move, Done and (mostly) Later. A tested pull request's card also has "Why?"
 * (the loop's evidence) and, when tests fail, "Show failures" (the output's tail), both shown in place. What was done
 * folds into one "done today" line: the watch's notes (with any files), what it closed and Odie's loops closed (with
 * Reopen), and jobs that finished. open: start unfolded (tests). */
export function NeedsYou({ items, footer, closed, notes = [], loopsDone = [], jobsDone = [], onAct, onReopen, onReopenLoop, open = false, empty }: {
  items: Need[] | null; footer: string; closed: WatchClosedItem[]; notes?: WatchNote[]; loopsDone?: LoopDone[]; jobsDone?: JobDone[];
  onAct: (need: Need, act: NeedAction) => void; onReopen: (id: number) => void; onReopenLoop?: (id: number) => void; open?: boolean;
  empty?: string;
}) {
  const [showClosed, setShowClosed] = useState(open);
  const [unfolded, setUnfolded] = useState<Record<string, "why" | "output" | undefined>>({});
  const [wholeStep, setWholeStep] = useState<Record<string, boolean>>({});  // "<ref>:<i>" -> the step's command shown whole
  const toggle = (ref: string, what: "why" | "output") => setUnfolded((u) => ({ ...u, [ref]: u[ref] === what ? undefined : what }));
  const doneCount = closed.length + notes.length + loopsDone.length + jobsDone.length;
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
          <div className="text-ui text-muted">{empty ?? "I check your mail every 30 minutes and tell you when something needs you."}</div>
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
                {n.why && <span className="text-small leading-[18px] text-muted mt-0.5 line-clamp-2">{n.why}</span>}
                {n.brief && <span className="text-small leading-[18px] text-ink-2 mt-1 line-clamp-3">{n.brief}</span>}
                {n.badge && <span className={`chip ${badgeTone(n.badge) === "warn" ? "chip-warn" : "chip-soft"} mt-1.5 inline-flex`}>{n.badge}</span>}
              </span>
            </button>
            {n.uses && <div className="min-[430px]:ml-12 text-small leading-[18px] text-muted">{n.uses}</div>}
            {!!n.may_read?.length && (
              <div className="min-[430px]:ml-12 text-small leading-[18px] text-muted break-all">
                May read: {n.may_read.join(", ")}, no web · read as plain files; hidden files and git history aren't available
              </div>
            )}
            {!!n.steps?.length && (
              <ul className="min-[430px]:ml-12 flex flex-col gap-2" aria-label="Steps it needed">
                {n.steps.map((st, i) => (
                  <li key={i} className="min-w-0">
                    <div className={`text-small leading-[18px] font-semibold ${st.allowed ? "text-ink-2" : "text-warn-ink"}`}>{st.words}</div>
                    <code className={`block mt-0.5 rounded-tile bg-well px-2.5 py-1.5 text-caption leading-4 font-mono text-muted break-all ${wholeStep[`${n.ref}:${i}`] ? "whitespace-pre-wrap" : "line-clamp-3"}`}>{st.raw}</code>
                    {st.raw.length > 120 && (
                      <button type="button" onClick={() => setWholeStep((w) => ({ ...w, [`${n.ref}:${i}`]: !w[`${n.ref}:${i}`] }))}
                        className="mt-0.5 text-small font-semibold text-ember-text underline underline-offset-2">{wholeStep[`${n.ref}:${i}`] ? "Show less" : "Show all"}</button>
                    )}
                  </li>
                ))}
              </ul>
            )}
            {!!n.evidence?.length && (
              <button type="button" onClick={() => toggle(n.ref, "why")} aria-expanded={unfolded[n.ref] === "why"}
                className="self-start min-[430px]:ml-12 text-small font-semibold text-ember-text underline underline-offset-2">Why?</button>
            )}
            {unfolded[n.ref] === "why" && (
              <ul className="min-[430px]:ml-12 flex flex-col gap-1 text-small leading-[18px] text-muted" aria-label="Why">
                {(n.evidence ?? []).map((e, i) => <li key={i} className="break-words"><span className="tabular-nums">{e.at.slice(11, 16)}</span> {e.fact}</li>)}
              </ul>
            )}
            {unfolded[n.ref] === "output" && n.output && (
              <pre className="min-[430px]:ml-12 max-h-[240px] overflow-auto rounded-tile bg-well px-3 py-2 text-caption leading-4 font-mono whitespace-pre-wrap break-words" aria-label="Failures">{n.output}</pre>
            )}
            {/* The move first and solid, then Done and Later, always on one row: a long move ends in "…" (its whole
                label is its title), Done and Later keep their size. Under the tile only on a wide phone or larger (430px up). */}
            <div className="flex gap-2 min-[430px]:pl-12" data-buttons="one-row">
              {buttonsOf(n).map((a, i) => (
                <button key={a.action + i} type="button" onClick={() => (a.action === "show_output" ? toggle(n.ref, "output") : onAct(n, a))} title={a.label}
                  className={i === 0 ? "pill pill-solid h-9 px-4 text-ui shadow-none min-w-0 shrink max-w-[60%]" : "pill h-9 px-3 text-ui shrink-0"}><span className="truncate">{a.label}</span></button>
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
          {showClosed && <WatchClosed items={loopsDone} onReopen={(id) => onReopenLoop?.(id)} />}
          {showClosed && <WatchClosed items={jobsDone} />}
        </div>
      )}
    </section>
  );
}
