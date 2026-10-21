import { Icon } from "./Tile";

export type WatchClosedItem = { id: number; title: string; why: string; closed: string };

/** Why the watch closed a reminder, as a line that reads as a sentence: "paid: confirmation mail 21 Oct" ->
 * "Paid: confirmation mail 21 Oct"; nothing said -> "Closed by Odie". */
export function whyLine(why: string): string {
  const said = (why || "").trim();
  if (!said) return "Closed by Odie";
  return said[0].toUpperCase() + said.slice(1);
}

/** To close's last rows: the reminders the watch closed in the last few days (a bill it saw paid, an order delivered),
 * in green with why, each with Reopen for when the watch got it wrong. Nothing closed -> nothing drawn. */
export function WatchClosed({ items, onReopen }: { items: WatchClosedItem[]; onReopen: (id: number) => void }) {
  if (!items.length) return null;
  return (
    <div className="mt-1 border-t border-line pt-1">
      {items.map((t) => (
        <div key={t.id} className="flex items-center gap-3 py-2.5 px-1">
          <span className="w-9 h-9 shrink-0 rounded-full grid place-items-center bg-good text-white" aria-hidden="true">
            <Icon name="check" size={18} stroke={2.6} />
          </span>
          <div className="flex-1 min-w-0">
            <div className="text-[15px] leading-[1.35] font-semibold break-words text-ink-2">{t.title}</div>
            <div className="text-[12.5px] leading-[17px] text-good mt-0.5">{whyLine(t.why)}</div>
          </div>
          <button type="button" onClick={() => onReopen(t.id)} className="pill h-8 px-3 text-[12.5px] shrink-0">Reopen</button>
        </div>
      ))}
    </div>
  );
}
