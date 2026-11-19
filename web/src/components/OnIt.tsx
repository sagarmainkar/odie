import { useRef, useState } from "react";
import { onItLine, type OnIt as OnItItem } from "../pulse";
import { pulseTaps, useListChanged } from "../tapGuard";
import { Icon } from "./Tile";

/** Pulse's "Odie is on it": the jobs going now (each with Stop) and the loops Odie is still working on (waiting for CI,
 *  a draft, someone else), one line each. Nothing on -> nothing drawn. `who` is whose Pulse it is ("Odie", "Mira"). */
export function OnIt({ items, who, onStop }: { items: OnItItem[]; who: string; onStop?: (jobId: string) => Promise<void> | void }) {
  const [stopping, setStopping] = useState<Record<string, boolean>>({});  // job id -> its Stop call is running
  const sent = useRef(new Set<string>());  // the same, at once: a double tap's second click comes before a redraw
  useListChanged(items.map((it) => it.id).join(" "));
  // Stop, for the job this row was drawn with. Ignored just after the rows moved, and while its call runs, so a
  // second tap never asks the server to stop a job that has already stopped.
  const stop = async (jobId: string) => {
    if (!onStop || !pulseTaps.ok() || sent.current.has(jobId)) return;
    sent.current.add(jobId);
    setStopping((m) => ({ ...m, [jobId]: true }));
    try {
      await onStop(jobId);
    } finally {
      sent.current.delete(jobId);
      setStopping((m) => ({ ...m, [jobId]: false }));
    }
  };
  if (!items.length) return null;
  return (
    <section className="flex flex-col gap-2.5" aria-label={`${who} is on it`}>
      <div className="section-head text-heading font-bold tracking-[-0.015em] px-1">{who} is on it <span className="text-dim font-semibold">({items.length})</span></div>
      <div className="glass rounded-card px-3 py-1">
        {items.map((it, i) => (
          <div key={it.id} className={`flex items-center gap-3 py-2.5 px-1 ${i ? "border-t border-line" : ""}`}>
            <span className="w-9 h-9 shrink-0 rounded-full grid place-items-center bg-well text-ink-2" aria-hidden="true"><Icon name="clock" size={17} /></span>
            <div className="flex-1 min-w-0">
              <div className="text-body leading-[1.35] font-semibold break-words text-ink-2">{it.title}</div>
              <div className="text-small leading-[17px] text-muted mt-0.5">{onItLine(it)}</div>
            </div>
            {it.stop && onStop && (
              <button type="button" onClick={() => void stop(it.stop as string)} disabled={!!stopping[it.stop]}
                className="pill h-8 px-3 text-small shrink-0 disabled:opacity-60">{stopping[it.stop] ? "Stopping…" : "Stop"}</button>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
