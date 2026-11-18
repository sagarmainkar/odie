import { onItLine, type OnIt as OnItItem } from "../pulse";
import { Icon } from "./Tile";

/** Pulse's "Odie is on it": the loops Odie is still working on (waiting for CI, a draft, someone else), one line each.
 *  Nothing on -> nothing drawn. `who` is whose Pulse it is ("Odie", "Mira"). */
export function OnIt({ items, who }: { items: OnItItem[]; who: string }) {
  if (!items.length) return null;
  return (
    <section className="flex flex-col gap-2.5" aria-label={`${who} is on it`}>
      <div className="text-heading font-bold tracking-[-0.015em] px-1">{who} is on it <span className="text-dim font-semibold">({items.length})</span></div>
      <div className="glass rounded-card px-3 py-1">
        {items.map((it, i) => (
          <div key={it.id} className={`flex items-center gap-3 py-2.5 px-1 ${i ? "border-t border-line" : ""}`}>
            <span className="w-9 h-9 shrink-0 rounded-full grid place-items-center bg-well text-ink-2" aria-hidden="true"><Icon name="clock" size={17} /></span>
            <div className="flex-1 min-w-0">
              <div className="text-body leading-[1.35] font-semibold break-words text-ink-2">{it.title}</div>
              <div className="text-small leading-[17px] text-muted mt-0.5">{onItLine(it)}</div>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
