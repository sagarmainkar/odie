import { useCallback, useEffect, useState } from "react";
import { getJSON } from "../api";
import { botHref, sortBots, type Bot, type JobAsk } from "../bots";
import { AskLine } from "./AskLine";
import { useLive } from "../live";
import { Creature, FuzzFilter } from "./Creature";

/** Today's Bots card (Fable's design, frame H): the team's creatures (those at work or waiting on you first), each
 * question a bot waits on (answered right here), each bot at work, and each bot that answered since you last looked. Tap a creature to talk to it; All bots opens the list. Hidden
 * while bots are off (the route answers 404). */
export function BotsCard() {
  const [bots, setBots] = useState<Bot[] | null>(null);
  const [asks, setAsks] = useState<JobAsk[]>([]);
  const load = useCallback(() => {
    getJSON<{ bots: Bot[] }>("/api/bots").then((r) => setBots(sortBots(r.bots))).catch(() => setBots(null));
    getJSON<{ asks?: JobAsk[] }>("/api/jobs").then((r) => setAsks(r.asks ?? [])).catch(() => setAsks([]));
  }, []);
  useEffect(load, [load]);
  useLive(useCallback((e: { type: string }) => { if (e.type === "bot_message" || e.type === "message") load(); }, [load]), load);
  useEffect(() => {
    if (!bots?.some((b) => b.working)) return;
    const t = setTimeout(load, 5000);
    return () => clearTimeout(t);
  }, [bots, load]);
  if (!bots || bots.length === 0) return null;
  const first = [...bots].sort((a, b) => Number(!!b.needs_you) - Number(!!a.needs_you) || Number(!!b.working) - Number(!!a.working));
  const working = bots.filter((b) => b.working && !b.needs_you);
  const answered = bots.filter((b) => b.unread && !b.working && !b.needs_you);
  return (
    <section className="glass rounded-[26px] px-4 py-3.5 flex flex-col gap-3">
      <FuzzFilter />
      <div className="flex items-center justify-between">
        <span className="text-[15px] font-semibold">Bots</span>
        <a href="#bots" className="text-[13px] text-ember-text font-semibold">All bots ›</a>
      </div>
      <div className="flex gap-3 overflow-x-auto no-scrollbar -mx-1 px-1 pb-1">
        {first.map((b) => (
          <a key={b.name} href={botHref(b)} className="flex flex-col items-center gap-1 w-[66px] shrink-0">
            <span className="relative">
              <Creature look={b.look} size={44} mood={b.needs_you ? "wants" : b.working ? "working" : ""} />
              {b.unread && <span className="absolute -top-0.5 -right-0.5 w-2.5 h-2.5 rounded-full bg-[var(--t-brand)]" />}
            </span>
            <span className="text-[11.5px] text-muted truncate w-full text-center">{b.name}</span>
          </a>
        ))}
      </div>
      {asks.map((a) => <AskLine key={a.id} a={a} onAnswered={load} />)}
      {working.map((b) => (
        <a key={b.name} href={botHref(b)} className="flex items-center gap-2.5 rounded-[16px] px-3 py-2 bg-well">
          <Creature look={b.look} size={26} mood="working" />
          <span className="min-w-0 flex-1">
            <span className="block text-[13px] font-semibold">{b.name} · at work</span>
            <span className="block text-[12.5px] text-muted truncate">{b.live}…</span>
          </span>
          <span aria-hidden="true" className="text-muted">›</span>
        </a>
      ))}
      {answered.map((b) => (
        <a key={b.name} href={botHref(b)} className="flex items-center gap-2.5 rounded-[16px] px-3 py-2 bg-well">
          <span className="relative"><Creature look={b.look} size={26} /><span className="absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full bg-[var(--t-brand)]" /></span>
          <span className="min-w-0 flex-1">
            <span className="block text-[13px] font-semibold">{b.name} answered</span>
            <span className="block text-[12.5px] text-muted truncate">{b.preview}</span>
          </span>
          <span aria-hidden="true" className="text-muted">›</span>
        </a>
      ))}
    </section>
  );
}
