import { useCallback, useEffect, useRef, useState } from "react";
import { getJSON, postJSON } from "../api";
import { botFromHash, type Bot, type Conversation, type ConvMessage } from "../bots";
import { useLive } from "../live";
import { BotDetails } from "../components/BotDetails";
import { BotDrawer } from "../components/BotDrawer";
import { Creature, FuzzFilter } from "../components/Creature";
import { LiveView } from "../components/LiveView";
import { MediaList } from "../components/MediaList";
import { TeamCard, TurnPill } from "../components/TeamCard";
import { Icon } from "../components/Tile";
import { YourMessage } from "../components/YourMessage";
import type { Media } from "../media";
import { ReplyText } from "./Chat";

type Loaded = { conversation: Conversation; bot: Bot; messages: ConvMessage[]; running: string | null };

/** Talking to a bot (Fable's design, frames B and C): Odie's chat screen, owned by the bot. Its header shows the
 * bot (tap the name for its details), the drawer switches bot and conversation, compose starts a new one. Each message
 * is answered by one of the bot's jobs: the team card follows it live, a question it waits on shows here with its
 * buttons, and the reply arrives as the bot's message. */
export function BotChat() {
  const [where, setWhere] = useState(() => botFromHash(location.hash));
  const [data, setData] = useState<Loaded | null>(null);
  const [bot, setBot] = useState<Bot | null>(null);
  const [drawer, setDrawer] = useState(false);
  const [details, setDetails] = useState(false);
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const [sending, setSending] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  const swipe = useRef<{ x: number; y: number } | null>(null);  // a swipe from the left edge opens the drawer (phone)

  useEffect(() => {
    const on = () => setWhere(botFromHash(location.hash));
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);

  const name = where?.bot ?? "";
  const conv = where?.conv ?? null;

  const load = useCallback(() => {
    if (!name) return;
    if (!conv) {  // the bot alone: its latest conversation, or a fresh start
      setData(null);
      getJSON<{ bot: Bot; conversations: Conversation[] }>(`/api/bots/${name}/conversations`).then((r) => {
        setBot(r.bot);
        if (r.conversations.length) location.replace(`#bot/${name}/${r.conversations[0].id}`);
      }).catch(() => setBot(null));
      return;
    }
    getJSON<Loaded>(`/api/conversations/${conv}`).then((r) => {
      setData(r);
      setBot(r.bot);
      if (r.conversation.unread) void postJSON(`/api/conversations/${conv}/read`, {}).catch(() => {});
    }).catch(() => setData(null));
  }, [name, conv]);
  useEffect(load, [load]);
  useLive(useCallback((e: { type: string; conv?: string }) => { if (e.type === "bot_message" && e.conv === conv) load(); }, [conv, load]), load);
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [data?.messages.length, data?.running]);

  async function send() {
    const said = text.trim();
    if (!said || !name) return;
    setSending(true); setError("");
    try {
      let id = conv;
      if (!id) {
        id = (await postJSON<{ id: string }>(`/api/bots/${name}/conversations`, {})).id;
      }
      const r = await fetch(`/api/conversations/${id}/messages`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: said }) });
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        setError(body.detail || "Couldn't send. Try again.");
        return;
      }
      setText("");
      if (id !== conv) location.hash = `#bot/${name}/${id}`;
      else load();
    } finally {
      setSending(false);
    }
  }

  async function fresh() {
    const { id } = await postJSON<{ id: string }>(`/api/bots/${name}/conversations`, {});
    location.hash = `#bot/${name}/${id}`;
  }

  if (!where) return null;
  const shown = data?.messages ?? [];
  const busy = !!data?.running;
  const model = bot?.model ? bot.model.model : "the chat's model";
  return (
    <div className="h-full flex">
      <FuzzFilter />
      <div className="hidden lg:block w-[320px] shrink-0 h-full border-r border-line bg-overlay backdrop-blur-xl">
        <BotDrawer current={name} conv={conv} />
      </div>
      {drawer && (
        <div className="lg:hidden fixed inset-0 z-40 flex" onClick={() => setDrawer(false)}>
          <div className="w-[86%] max-w-[360px] h-full glass glass-solid" onClick={(e) => e.stopPropagation()}>
            <BotDrawer current={name} conv={conv} onPick={() => setDrawer(false)} />
          </div>
          <div className="flex-1 bg-overlay" />
        </div>
      )}
      <div className="flex-1 min-w-0 h-full flex flex-col max-w-[520px] md:max-w-[720px] lg:max-w-[860px] mx-auto"
        onTouchStart={(e) => { const t = e.touches[0]; swipe.current = t.clientX < 24 ? { x: t.clientX, y: t.clientY } : null; }}
        onTouchMove={(e) => { const s = swipe.current; const t = e.touches[0]; if (s && t.clientX - s.x > 60 && Math.abs(t.clientY - s.y) < 40) { swipe.current = null; setDrawer(true); } }}>
        <div className="flex items-center gap-2.5 px-[14px] safe-top pb-2">
          <button onClick={() => setDrawer(true)} aria-label="Bots and conversations" className="pill w-11 px-0 lg:hidden!"><Icon name="menu" /></button>
          <button onClick={() => bot && setDetails(true)} className="flex items-center gap-2.5 min-w-0 text-left">
            <Creature look={bot?.look} size={38} mood={bot?.needs_you ? "wants" : busy ? "working" : ""} />
            <span className="min-w-0">
              <span className="block text-[16px] font-semibold truncate">{name}</span>
              <span className="block text-[12px] text-muted truncate">{model}{bot?.powers?.length ? ` · ${bot.powers.join(", ")}` : ""}</span>
            </span>
          </button>
          <button onClick={() => void fresh()} aria-label="New conversation" className="ml-auto pill w-11 px-0"><Icon name="plus" /></button>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto no-scrollbar px-[14px] pb-4 flex flex-col gap-3">
          {data && <div className="text-center text-[12px] text-muted pt-1">{data.conversation.origin === "chat" ? "Asked by Odie from your chat" : data.conversation.origin === "routine" ? `Runs by itself · ${data.conversation.title}` : data.conversation.title}</div>}
          {!conv && bot && <Hello bot={bot} onPick={(q) => setText(q)} />}
          {shown.map((m) => <Message key={m.id} m={m} bot={bot} onAnswered={load} />)}
          {busy && data?.running && <TeamCard job={data.running} />}
          <div ref={end} />
        </div>

        <div className="px-[14px] pb-4">
          {error && <div className="mb-2 text-[13px] text-ember-text">{error}</div>}
          <div className="glass rounded-[26px] flex items-end gap-2 px-3 py-2">
            <textarea value={text} onChange={(e) => setText(e.target.value)} rows={1} placeholder={`Message ${name}`}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && window.matchMedia("(min-width: 1024px)").matches) { e.preventDefault(); void send(); } }}
              className="flex-1 bg-transparent outline-none resize-none text-[15.5px] leading-[1.45] max-h-[160px] py-2" />
            <button onClick={() => void send()} disabled={sending || busy || !text.trim()} aria-label="Send"
              className="w-10 h-10 rounded-full bg-ember text-on-ember grid place-items-center disabled:opacity-40"><Icon name="up" /></button>
          </div>
          {busy && <div className="mt-1.5 text-center text-[12px] text-muted">{name} is answering. You can leave: the answer comes here, with a push.</div>}
        </div>
      </div>
      {details && bot && <BotDetails bot={bot} onClose={(changed) => { setDetails(false); if (changed) load(); }} />}
    </div>
  );
}

/** An empty conversation: the creature large, its role and powers, and three ways to start. */
function Hello({ bot, onPick }: { bot: Bot; onPick: (q: string) => void }) {
  const starts = bot.chief
    ? ["Compare two options for me from every side", "Is this claim true? Check it properly", "Plan a weekend trip with the team"]
    : [`What can you do for me, ${bot.name}?`, "Start with what you know about me", "Here's my first question:"];
  return (
    <div className="flex flex-col items-center text-center gap-2 pt-10">
      <Creature look={bot.look} size={96} />
      <div className="text-[20px] font-bold">{bot.name}</div>
      <div className="text-[14px] text-muted max-w-[320px]">{bot.role}</div>
      {bot.powers.length > 0 && <div className="text-[12px] text-muted">Can use: {bot.powers.join(", ")}</div>}
      <div className="mt-3 flex flex-col gap-2 w-full max-w-[340px]">
        {starts.map((q) => <button key={q} onClick={() => onPick(q)} className="glass rounded-[16px] px-3.5 py-2.5 text-[14px] text-left">{q}</button>)}
      </div>
    </div>
  );
}

function Message({ m, bot, onAnswered }: { m: ConvMessage; bot: Bot | null; onAnswered: () => void }) {
  if (m.role === "user") return <YourMessage text={m.text} />;
  if (m.role === "ask") return <AskCard m={m} onAnswered={onAnswered} />;
  if (m.role === "note") return <div className="self-center max-w-[90%] text-center text-[12px] text-muted px-3 py-1 rounded-full bg-well">{m.text}</div>;
  const files = Array.isArray(m.media) ? (m.media as unknown as Media[]) : [];
  return (
    <div className="flex flex-col gap-1.5 max-w-[92%]">
      <div className="flex items-center gap-2 text-[12.5px] text-muted">
        <Creature look={bot?.look} size={22} /><b className="text-ink-2">{bot?.name ?? "bot"}</b>
        <span>· {new Date(m.ts).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</span>
      </div>
      {m.job_id && <TurnPill job={m.job_id} />}
      <ReplyText text={m.text} />
      {files.length > 0 && <MediaList items={files} />}
    </div>
  );
}

/** A question the bot waits on, answered here (only the app's buttons answer: odie/workers/asks.py). */
function AskCard({ m, onAnswered }: { m: ConvMessage; onAnswered: () => void }) {
  const media = (m.media && !Array.isArray(m.media) ? m.media : {}) as { ask?: string; kind?: string; why?: string | null; status?: string; card?: { tab?: string; site?: string; url?: string } | null };
  const [live, setLive] = useState(false);
  const open = media.status === "open";
  async function answer(said: "yes" | "no") {
    if (!media.ask) return;
    await postJSON(`/api/jobs/asks/${media.ask}`, { answer: said }).catch(() => {});
    onAnswered();
  }
  if (media.kind === "secret") return <SecretAsk m={m} ask={media.ask ?? ""} open={open} status={media.status} why={media.why} onAnswered={onAnswered} />;
  // A sign-in that lapsed (Odie restarted, or no answer in time): the page can still be opened, to sign in for next time.
  const reopen = !open && media.kind === "sign_in" && media.status === "expired" && !!media.card?.tab;
  const settled = media.status === "yes" ? "You allowed it." : media.status === "no" ? "You said no." : "No answer in time: it counted as no.";
  return (
    <div className={`rounded-[22px] px-4 py-3 flex flex-col gap-2 border ${open ? "bg-warn-tint border-[rgba(255,178,63,.3)]" : "glass border-transparent"}`}>
      <div className="text-[14.5px] font-semibold">{media.kind === "sign_in" ? "🔑 " : "✋ "}{m.text}</div>
      {media.why && <div className="text-[12.5px] text-muted">{media.why}</div>}
      {open ? (
        <div className="flex gap-2">
          {media.kind === "sign_in" ? (
            <>
              {media.card?.tab && <button onClick={() => setLive(true)} className="h-10 px-4 rounded-[14px] bg-ember text-on-ember font-semibold text-[14px]">Sign in</button>}
              <button onClick={() => void answer("yes")} className="pill h-10 px-4 text-[14px]">Done</button>
              <button onClick={() => void answer("no")} className="pill h-10 px-4 text-[14px]">Skip</button>
            </>
          ) : (
            <>
              <button onClick={() => void answer("no")} className="pill h-10 px-4 text-[14px]">Deny</button>
              <button onClick={() => void answer("yes")} className="h-10 px-4 rounded-[14px] bg-ember text-on-ember font-semibold text-[14px]">Allow</button>
            </>
          )}
        </div>
      ) : <div className="text-[12.5px] text-muted">{settled}</div>}
      {reopen && <button onClick={() => setLive(true)} className="self-start pill h-9 px-3 text-[13px]">Open the page and sign in</button>}
      {live && media.card?.tab && <LiveView tab={media.card.tab} site={media.card.site ?? ""} start={reopen ? media.card.url ?? "" : undefined} chat={false}
        onClose={(r) => { setLive(false); if (r?.done && open) void answer("yes"); }} />}
    </div>
  );
}

/** "Type a secret for me": a code, a PIN, a password the bot needs in a field. What you type goes straight into that
 * field on the page; the bot is told only that it was typed, and it is kept nowhere (odie/workers/asks.py). */
function SecretAsk({ m, ask, open, status, why, onAnswered }: { m: ConvMessage; ask: string; open: boolean; status?: string; why?: string | null; onAnswered: () => void }) {
  const [value, setValue] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function send(said: "yes" | "no") {
    setBusy(true); setError("");
    const r = await fetch(`/api/jobs/asks/${ask}`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(said === "yes" ? { answer: "yes", secret: value } : { answer: "no" }) });
    setBusy(false);
    if (!r.ok) { const b = await r.json().catch(() => ({})); setError(b.detail || "That didn't go in. Try again."); return; }
    setValue("");
    onAnswered();
  }
  return (
    <div className={`rounded-[22px] px-4 py-3 flex flex-col gap-2 border ${open ? "bg-warn-tint border-[rgba(255,178,63,.3)]" : "glass border-transparent"}`}>
      <div className="text-[14.5px] font-semibold">🔒 {m.text}</div>
      {why && <div className="text-[12.5px] text-muted">{why}</div>}
      {open ? (
        <>
          <input type="password" autoComplete="one-time-code" value={value} onChange={(e) => setValue(e.target.value)} maxLength={200}
            placeholder="Type it here" className="h-11 rounded-[14px] border border-line-2 bg-transparent px-3 text-[15px]" />
          <div className="text-[12px] text-muted">It goes straight into the page. The bot never sees it, and Odie keeps it nowhere.</div>
          {error && <div className="text-[13px] text-ember-text">{error}</div>}
          <div className="flex gap-2">
            <button disabled={busy} onClick={() => void send("no")} className="pill h-10 px-4 text-[14px]">Skip</button>
            <button disabled={busy || !value} onClick={() => void send("yes")} className="h-10 px-4 rounded-[14px] bg-ember text-on-ember font-semibold text-[14px] disabled:opacity-50">Type it in</button>
          </div>
        </>
      ) : <div className="text-[12.5px] text-muted">{status === "yes" ? "Typed in." : status === "no" ? "You skipped it." : "No answer in time."}</div>}
    </div>
  );
}
