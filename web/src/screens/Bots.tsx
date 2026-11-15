import { useCallback, useEffect, useState } from "react";
import { getJSON } from "../api";
import { botHref, matches, rowLine, sortBots, whenWords, type Bot } from "../bots";
import { userLocale } from "../locale";
import { useLive } from "../live";
import { Creature, FuzzFilter } from "../components/Creature";
import { NewBotSheet } from "../components/NewBotSheet";
import { Icon } from "../components/Tile";

/** Your bots (Fable's design, frame A): Odie pinned first, then the team, each with its creature, role, time and last
 * line; a live line while it works, an amber chip while it waits on your tap, a dot when it said something new.
 * Search sits at the bottom; + asks the chief to make a bot. */
export function Bots() {
  const [bots, setBots] = useState<Bot[] | null>(null);
  const [q, setQ] = useState("");
  const [adding, setAdding] = useState(false);
  const load = useCallback(() => { getJSON<{ bots: Bot[] }>("/api/bots").then((r) => setBots(r.bots)).catch(() => setBots([])); }, []);
  useEffect(load, [load]);
  useLive(useCallback((e: { type: string }) => { if (e.type === "bot_message" || e.type === "message") load(); }, [load]), load);
  useEffect(() => {  // a bot at work: its live line moves on
    if (!bots?.some((b) => b.working)) return;
    const t = setTimeout(load, 4000);
    return () => clearTimeout(t);
  }, [bots, load]);

  const shown = sortBots((bots ?? []).filter((b) => matches(b, q)));
  const working = (bots ?? []).filter((b) => b.working).length;
  const waiting = (bots ?? []).filter((b) => b.needs_you).length;
  const locale = userLocale();
  return (
    <div className="h-full flex flex-col">
      <FuzzFilter />
      <div className="flex-1 min-h-0 overflow-y-auto no-scrollbar px-[18px] lg:px-8 safe-top pb-6 flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <a href="#today" aria-label="Back to Today" className="pill w-11 px-0 lg:hidden!"><Icon name="back" /></a>
          <span className="hidden lg:block" />
          <button onClick={() => setAdding(true)} aria-label="Make a bot" className="pill w-11 px-0"><Icon name="plus" /></button>
        </div>
        <div>
          <h1 className="text-[34px] leading-[1.1] font-bold tracking-[-0.025em]">Your <span className="serif text-[40px] text-ink-2">bots</span></h1>
          {(working > 0 || waiting > 0) && (
            <div className="mt-2 flex gap-2">
              {working > 0 && <span className="chip chip-soft">{working} working</span>}
              {waiting > 0 && <span className="chip chip-warn">{waiting} need{waiting === 1 ? "s" : ""} you</span>}
            </div>
          )}
        </div>

        <a href="#chat" className="glass rounded-[22px] flex items-center gap-3 px-3.5 py-3 active:scale-[.99]">
          <Creature odie size={48} />
          <div className="flex-1 min-w-0">
            <div className="text-[16px] font-semibold">Odie</div>
            <div className="text-[13px] text-muted truncate">Your assistant · memory, mail, calendar</div>
          </div>
        </a>

        <div className="px-1 flex items-center justify-between text-[12px] font-semibold text-muted uppercase tracking-wide">
          <span>Team</span><span>{(bots ?? []).length} bots</span>
        </div>
        <div className="glass rounded-[24px] overflow-hidden">
          {bots === null && <div className="px-4 py-5 text-[14px] text-muted">…</div>}
          {shown.map((b) => (
            <a key={b.name} href={botHref(b)} className="flex items-center gap-3 px-3.5 py-3 border-b border-line last:border-b-0 active:bg-well">
              <Creature look={b.look} size={50} mood={b.needs_you ? "wants" : b.working ? "working" : ""} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-[16px] font-semibold truncate">{b.name}</span>
                  <span className="ml-auto shrink-0 text-[12px] text-muted">
                    {b.needs_you ? <span className="chip chip-warn !py-0.5 !text-[11px]">Needs your tap</span> : b.working ? "now" : whenWords(b.updated_at, undefined, locale)}
                  </span>
                </div>
                <div className="text-[12.5px] text-muted truncate">{b.role}</div>
                <div className={`text-[13.5px] truncate ${b.unread ? "font-semibold text-ink" : "text-ink-2"} ${b.working ? "text-ember-text" : ""}`}>
                  {b.unread && !b.working && <span className="inline-block w-2 h-2 rounded-full bg-[var(--t-brand)] mr-1.5 align-middle" />}
                  {rowLine(b)}
                </div>
              </div>
            </a>
          ))}
          {bots !== null && shown.length === 0 && <div className="px-4 py-5 text-[14px] text-muted">No bot matches “{q}”.</div>}
        </div>
        <button onClick={() => setAdding(true)} className="rounded-[22px] border border-dashed border-line-2 px-4 py-3.5 text-left">
          <div className="text-[15px] font-semibold">Make a bot of your own</div>
          <div className="text-[13px] text-muted">Say what it should do; the chief writes its role and instructions, and you check them.</div>
        </button>
      </div>
      <div className="px-[18px] lg:px-8 pb-4 pt-2">
        <label className="glass rounded-full flex items-center gap-2 px-4 h-12">
          <Icon name="search" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search bots" className="flex-1 bg-transparent outline-none text-[15px]" />
        </label>
      </div>
      {adding && <NewBotSheet onClose={() => setAdding(false)} />}
    </div>
  );
}
