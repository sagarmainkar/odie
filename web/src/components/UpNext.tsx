import { motion } from "framer-motion";
import { dateParts, relative, sourceText, subline, timeText, type UpItem } from "../upnext";
import { EventArt, KIND_LABEL, kindVars } from "./EventArt";
import { Icon } from "./Tile";

const ask = (q: string) => { location.hash = `#chat?q=${encodeURIComponent(q)}`; };

/** The next thing coming up, large: its kind's illustration, the title, and a date card with the day as a big number. */
function Hero({ it }: { it: UpItem }) {
  const d = dateParts(it.date);
  const line = subline(it);
  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35, ease: [0.2, 0.8, 0.2, 1] }}
      className="kind-card relative rounded-[30px] p-4 overflow-hidden border shadow-[0_18px_40px_-24px_rgba(40,30,70,.45)]" style={kindVars(it.kind) as React.CSSProperties}>
      <div className="flex items-start gap-2">
        <div className="flex-1 min-w-0 pt-1">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="chip kind-chip text-ink-2">{KIND_LABEL[it.kind] ?? "Event"}</span>
            <span className="text-[11.5px] text-muted">{sourceText(it)}</span>
          </div>
          <div className="mt-2.5 text-[27px] leading-[1.08] font-extrabold italic tracking-[-0.02em] text-ink line-clamp-3">{it.title}</div>
          {line && <div className="mt-1.5 text-[13.5px] text-ink-2 truncate">{line}</div>}
        </div>
        <div className="shrink-0 -mr-1 -mt-1 drop-shadow-[0_10px_14px_rgba(40,30,70,.18)]"><EventArt kind={it.kind} size={112} /></div>
      </div>
      <div className="kind-inner mt-3 rounded-[24px] backdrop-blur-md border px-4 pt-3 pb-3.5">
        <div className="flex items-center justify-between text-[13.5px] font-semibold text-ink-2">
          <span>{d.month}</span><span className="text-muted">{d.weekday}</span>
        </div>
        <div className="flex items-end justify-between gap-3">
          <div className="text-[84px] leading-[0.95] font-extrabold tracking-[-0.05em] tabular-nums text-ink">{d.day}</div>
          <div className="text-right pb-2">
            <div className="text-[19px] font-bold tabular-nums">{timeText(it)}</div>
            <div className="text-[13px] font-semibold text-ember-text">{relative(it)}</div>
          </div>
        </div>
        <button type="button" onClick={() => ask(it.ask)} className="mt-1 pill pill-solid h-10 text-[14px] shadow-none">
          <Icon name="spark" size={15} /> Ask about it
        </button>
      </div>
    </motion.div>
  );
}

function Mini({ it }: { it: UpItem }) {
  const d = dateParts(it.date);
  return (
    <button type="button" onClick={() => ask(it.ask)} className="kind-card snap-start shrink-0 w-[152px] rounded-[24px] p-3 text-left border flex flex-col active:scale-[.98] transition-transform"
      style={kindVars(it.kind) as React.CSSProperties}>
      <div className="flex items-start justify-between">
        <div>
          <div className="text-[11.5px] font-semibold text-muted">{d.short}</div>
          <div className="text-[30px] leading-none font-extrabold tracking-[-0.04em] tabular-nums">{d.day}</div>
        </div>
        <EventArt kind={it.kind} size={54} />
      </div>
      <div className="mt-2 text-[14px] leading-[18px] font-semibold line-clamp-2 min-h-[36px]">{it.title}</div>
      <div className="mt-1 text-[12px] text-muted truncate">{it.amount != null ? subline(it) : timeText(it)}</div>
    </button>
  );
}

/** Today: what's coming up in the next two weeks, from the calendar, SMS, mail and tasks. */
export function UpNext({ items, loading }: { items: UpItem[] | null; loading: boolean }) {
  if (loading && !items) return <div className="h-[300px] rounded-[30px] glass animate-pulse" aria-label="Loading" />;
  if (!items) return null;
  if (items.length === 0) {
    return (
      <div className="rounded-[30px] p-4 flex items-center gap-3 glass">
        <EventArt kind="general" size={64} />
        <div><b className="text-[15px]">Nothing coming up</b><div className="text-[13px] text-muted">Nothing in the next two weeks. Reminders, and events from a connected calendar, show here.</div></div>
      </div>
    );
  }
  const [first, ...rest] = items;
  return (
    <section className="flex flex-col gap-2.5">
      <div className="text-[13px] font-bold text-muted px-1.5">Up next</div>
      <Hero it={first} />
      {rest.length > 0 && (
        <div className="flex gap-2.5 overflow-x-auto no-scrollbar snap-x -mx-[18px] px-[18px] pb-1">
          {rest.slice(0, 14).map((it) => <Mini key={it.id} it={it} />)}
          <span className="shrink-0 w-1" />
        </div>
      )}
    </section>
  );
}
