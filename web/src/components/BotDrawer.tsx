import { useCallback, useEffect, useState } from "react";
import { getJSON } from "../api";
import { sortBots, whenWords, type Bot, type Conversation } from "../bots";
import { useLive } from "../live";
import { userLocale } from "../locale";
import { Creature } from "./Creature";
import { NewBotSheet } from "./NewBotSheet";
import { Icon } from "./Tile";

/** Switching bots (Fable's design, frame D): a strip of avatars down the left (Today, Odie, the chief, the team, +,
 * all bots), and beside it the chosen bot's conversations with New conversation. On a phone it slides in from the left;
 * on a desktop the bot chat keeps it open as two columns. */
export function BotDrawer({ current, conv, onPick }: { current: string; conv: string | null; onPick?: () => void }) {
  const [bots, setBots] = useState<Bot[]>([]);
  const [chosen, setChosen] = useState(current);
  const [list, setList] = useState<Conversation[] | null>(null);
  const [adding, setAdding] = useState(false);
  useEffect(() => setChosen(current), [current]);
  const loadBots = useCallback(() => { getJSON<{ bots: Bot[] }>("/api/bots").then((r) => setBots(sortBots(r.bots))).catch(() => {}); }, []);
  const loadList = useCallback(() => {
    getJSON<{ conversations: Conversation[] }>(`/api/bots/${chosen}/conversations`).then((r) => setList(r.conversations)).catch(() => setList([]));
  }, [chosen]);
  useEffect(loadBots, [loadBots]);
  useEffect(loadList, [loadList]);
  useLive(useCallback((e: { type: string }) => { if (e.type === "bot_message") { loadBots(); loadList(); } }, [loadBots, loadList]));
  const bot = bots.find((b) => b.name === chosen);
  const locale = userLocale();

  async function remove(c: Conversation) {
    if (!confirm(`Delete "${c.title}"? Its messages go; what the bot did stays in its record.`)) return;
    const r = await fetch(`/api/conversations/${c.id}`, { method: "DELETE" });
    if (!r.ok) { alert(((await r.json().catch(() => ({}))) as { detail?: string }).detail ?? "Couldn't delete it."); return; }
    location.hash = `#bot/${c.bot}/new`;
    loadList();
  }

  function fresh() {  // the conversation is made on its first message
    location.hash = `#bot/${chosen}/new`;
    onPick?.();
  }

  return (
    <div className="h-full flex">
      <div className="w-[68px] shrink-0 h-full overflow-y-auto no-scrollbar flex flex-col items-center gap-3 py-3 border-r border-line safe-top">
        <a href="#today" aria-label="Today" className="flex flex-col items-center gap-0.5 text-[10.5px] text-muted font-semibold" onClick={onPick}>
          <span className="pill w-11 px-0"><Icon name="sun" /></span>Today
        </a>
        <a href="#chat" aria-label="Odie" onClick={onPick}><Creature odie size={40} /></a>
        <div className="w-8 border-t border-line" />
        {bots.map((b) => (
          <button key={b.name} onClick={() => setChosen(b.name)} aria-label={b.name} className="relative">
            <Creature look={b.look} size={40} mood={b.name === chosen ? "selected" : b.needs_you ? "wants" : b.working ? "working" : ""} />
            {b.unread && <span className="absolute -top-0.5 -right-0.5 w-2.5 h-2.5 rounded-full bg-[var(--t-brand)] ring-2 ring-[var(--t-bg,white)]" />}
          </button>
        ))}
        <button onClick={() => setAdding(true)} aria-label="Make a bot" className="pill w-10 h-10 px-0"><Icon name="plus" /></button>
        <a href="#bots" aria-label="All bots" className="flex flex-col items-center gap-0.5 text-[10.5px] text-muted font-semibold lg:hidden!" onClick={onPick}>
          <span className="pill w-10 h-10 px-0 text-[13px]">All</span>bots
        </a>
      </div>
      <div className="flex-1 min-w-0 h-full overflow-y-auto no-scrollbar px-3 py-3 safe-top flex flex-col gap-2">
        {bot && (
          <div className="flex items-center gap-2.5 px-1 py-1">
            <Creature look={bot.look} size={34} />
            <div className="min-w-0">
              <div className="text-[15px] font-semibold truncate">{bot.name}</div>
              <div className="text-[12px] text-muted truncate">{bot.role}</div>
            </div>
          </div>
        )}
        <button onClick={fresh} className="h-10 rounded-[14px] bg-ember text-on-ember font-semibold text-[14px] flex items-center justify-center gap-1.5"><Icon name="plus" size={16} />New conversation</button>
        {list?.length === 0 && <div className="px-1 text-[13px] text-muted">No conversations yet.</div>}
        {(list ?? []).some((c) => c.origin === "routine") && <div className="px-1 pt-1 text-[11.5px] font-semibold text-muted uppercase tracking-wide">Runs by itself</div>}
        {[...(list ?? []).filter((c) => c.origin === "routine"), ...(list ?? []).filter((c) => c.origin !== "routine")].map((c, i, all) => (
          <div key={c.id} className="contents">
          {i > 0 && all[i - 1].origin === "routine" && c.origin !== "routine" && <div className="px-1 pt-2 text-[11.5px] font-semibold text-muted uppercase tracking-wide">Conversations</div>}
          <a href={`#bot/${c.bot}/${c.id}`} onClick={onPick}
            className={`rounded-[14px] px-2.5 py-2 ${c.id === conv ? "bg-well" : "active:bg-well"}`}>
            <div className="flex items-center gap-2">
              <span className={`text-[14px] truncate ${c.unread ? "font-bold" : "font-medium"}`}>{c.title}</span>
              <span className="ml-auto shrink-0 text-[11.5px] text-muted">{whenWords(c.updated_at, undefined, locale)}</span>
            </div>
            <div className="text-[12.5px] text-muted truncate">{c.origin === "chat" ? "Asked by Odie from your chat · " : c.origin === "routine" ? "⟳ " : ""}{c.preview}</div>
          </a>
          {c.id === conv && c.origin !== "routine" && (
            <button onClick={() => void remove(c)} className="self-start ml-2.5 -mt-1 text-[12px] text-muted underline underline-offset-2">Delete this conversation</button>
          )}
          </div>
        ))}
      </div>
      {adding && <NewBotSheet onClose={() => setAdding(false)} />}
    </div>
  );
}
