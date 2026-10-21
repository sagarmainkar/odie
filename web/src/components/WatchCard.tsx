import { postJSON, todayISO } from "../api";
import { InlineText } from "../blocks/InlineText";
import { footer, watchRow, type WatchCardData } from "../watch";
import { Icon, Tile } from "./Tile";
import { SourceBadges } from "./SourceBadges";

const ask = (q: string) => { location.hash = `#chat?q=${encodeURIComponent(q)}`; };

/** Today's "Inbox & calendar": what the background watch found that needs the user, the next events, and when it last
 * checked (or what isn't working). A tap opens chat about an item; Done clears it for good. */
export function WatchCard({ card, onChange }: { card: WatchCardData; onChange: () => void }) {
  const items = card.needs_you.filter((i) => !i.done);
  if (card.off && !items.length && !card.events.length) {
    return (
      <section className="glass rounded-[26px] px-4 py-3.5 flex flex-col gap-1">
        <div className="text-[15px] font-semibold">Inbox & calendar</div>
        <div className="text-[13.5px] leading-[19px] text-muted">
          {card.off}{card.off.startsWith("Connect") && <> <a href="#settings" className="text-ember-text font-medium">Settings</a></>}
        </div>
      </section>
    );
  }
  async function done(ref: string) { await postJSON("/api/watch/done", { ref }); onChange(); }
  return (
    <section className="glass rounded-[26px] px-4 py-3.5 flex flex-col gap-2.5" aria-label="Inbox and calendar">
      <div className="flex items-baseline gap-2">
        <div className="text-[15px] font-semibold flex-1">Inbox & calendar</div>
        {card.line && <div className="text-[12.5px] text-muted truncate max-w-[60%]">{card.line}</div>}
      </div>
      {items.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <div className="text-[12px] font-semibold text-warn-ink uppercase tracking-[0.04em]">Needs you</div>
          {items.map((i) => {
            const row = watchRow(i, todayISO());
            return (
              <div key={i.ref} className="flex items-center gap-3 py-1.5">
                {row.lead.kind === "tile" ? <Tile icon={row.lead.icon} color={row.lead.color} /> : (
                  <span className="w-9 h-9 shrink-0 rounded-full grid place-items-center text-white text-[15px] font-bold" style={{ background: row.lead.colour }} aria-hidden="true">{row.lead.letter}</span>
                )}
                <button type="button" onClick={() => ask(row.run)} className="flex-1 min-w-0 text-left">
                  <div className="text-[14.5px] font-semibold leading-5 break-words">{row.title}<SourceBadges badges={i.badges} /></div>
                  {row.subtitle && <div className="text-[12.5px] leading-[17px] text-muted mt-0.5 line-clamp-2"><InlineText text={row.subtitle} /></div>}
                </button>
                {row.value && <span className="shrink-0 text-[12.5px] text-muted tabular-nums">{row.value}</span>}
                <button type="button" onClick={() => void done(i.ref)} aria-label="Done"
                  className="hit w-[34px] h-[34px] shrink-0 rounded-full grid place-items-center border-2 border-dashed border-dim text-transparent"><Icon name="check" size={18} stroke={2.6} /></button>
              </div>
            );
          })}
        </div>
      )}
      {card.events.length > 0 && (
        <div className="flex flex-col gap-1">
          <div className="text-[12px] font-semibold text-muted uppercase tracking-[0.04em]">Next</div>
          {card.events.slice(0, 3).map((e) => (
            <div key={e.id} className="text-[14px] flex gap-2"><span className="font-mono text-muted">{e.start.slice(11, 16)}</span><span className="truncate">{e.title}</span></div>
          ))}
        </div>
      )}
      {(card.off || card.checked_at) && <div className="text-[12px] text-dim">{card.off || footer(card, new Date())}</div>}
    </section>
  );
}
