import { useCallback, useEffect, useState } from "react";
import { getJSON, postJSON } from "../api";
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

  async function fresh() {
    const { id } = await postJSON<{ id: string }>(`/api/bots/${chosen}/conversations`, {});
    location.hash = `#bot/${chosen}/${id}`;
    onPick?.();
  }

  return (
    <div className="h-full flex">
      <div className="w-[68px] shrink-0 h-full overflow-y-auto no-scrollbar flex flex-col items-center gap-3 py-3 border-r border-line safe-top">
        <a href="#today" aria-label="Today" className="pill w-11 px-0" onClick={onPick}><Icon name="sun" /></a>
        <a href="#chat" aria-label="Odie" onClick={onPick}><Creature odie size={40} /></a>
        <div className="w-8 border-t border-line" />
        {bots.map((b) => (
          <button key={b.name} onClick={() => setChosen(b.name)} aria-label={b.name} className="relative">
            <Creature look={b.look} size={40} mood={b.name === chosen ? "selected" : b.needs_you ? "wants" : b.working ? "working" : ""} />
            {b.unread && <span className="absolute -top-0.5 -right-0.5 w-2.5 h-2.5 rounded-full bg-[var(--t-brand)] ring-2 ring-[var(--t-bg,white)]" />}
          </button>
        ))}
        <button onClick={() => setAdding(true)} aria-label="Make a bot" className="pill w-10 h-10 px-0"><Icon name="plus" /></button>
        <a href="#bots" aria-label="All bots" className="pill w-10 h-10 px-0 lg:hidden!" onClick={onPick}><Icon name="menu" /></a>
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
        <button onClick={() => void fresh()} className="h-10 rounded-[14px] bg-ember text-on-ember font-semibold text-[14px] flex items-center justify-center gap-1.5"><Icon name="plus" size={16} />New conversation</button>
        {list?.length === 0 && <div className="px-1 text-[13px] text-muted">No conversations yet.</div>}
        {list?.map((c) => (
          <a key={c.id} href={`#bot/${c.bot}/${c.id}`} onClick={onPick}
            className={`rounded-[14px] px-2.5 py-2 ${c.id === conv ? "bg-well" : "active:bg-well"}`}>
            <div className="flex items-center gap-2">
              <span className={`text-[14px] truncate ${c.unread ? "font-bold" : "font-medium"}`}>{c.title}</span>
              <span className="ml-auto shrink-0 text-[11.5px] text-muted">{whenWords(c.updated_at, undefined, locale)}</span>
            </div>
            <div className="text-[12.5px] text-muted truncate">{c.origin === "chat" ? "Asked by Odie from your chat · " : ""}{c.preview}</div>
          </a>
        ))}
      </div>
      {adding && <NewBotSheet onClose={() => setAdding(false)} />}
    </div>
  );
}
