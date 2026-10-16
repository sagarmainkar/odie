import { AnimatePresence, motion } from "framer-motion";
import { badge } from "../watch";
import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useLive } from "../live";
import { has, useCaps, userCountry } from "../capabilities";
import { ideasFor } from "../ideas";
import { getJSON, postJSON, todayISO } from "../api";
import { speak, stopSpeaking } from "../voice";
import { usePersona } from "../persona";
import { TalkMode } from "../components/TalkMode";
import { SpeakingBars } from "../components/Orb";
import { Avatar } from "../components/Avatar";
import { Orb } from "../components/Orb";
import { Icon as Glyph, Tile } from "../components/Tile";
import { greetingParts } from "../greeting";
import { Steps, type Tool } from "../components/Steps";
import { replyLine, type ReplyUsage } from "../usage";
import { ToBody } from "../components/ToBody";
import { CodeBlock } from "../components/CodeBlock";
import { CopyButton } from "../components/CopyButton";
import { howChatShowsFence } from "../blocks/fenceShown";
import { Enlarge } from "../components/Enlarge";
import { SvgBlock } from "../components/SvgBlock";
import { Blocks } from "../blocks/Blocks";
import { BlocksFence } from "../blocks/BlocksFence";
import { ReplyPlace } from "../blocks/SavedPlace";
import { ChatActions } from "../blocks/ChatActions";
import { MarkdownSpan } from "../blocks/InlineText";
import { remarkInline } from "../blocks/inlineSyntax";
import type { OrbState } from "../components/Orb";
import { streamChat, type ChatEvent } from "../sse";
import { ConnectCard } from "../components/ConnectCard";
import { splitConnect } from "../google";
import { Star, ThreadsSheet, ThreadsSidebar } from "../components/ThreadsSheet";
import { useWide } from "../layout";
import { belongsHere, type Thread } from "../threads";
import { plainMath } from "../plainMath";
import { liftOneLineFences } from "../blocks/oneLineFence";
import { tidyStrayBlocks } from "../blocks/strayBlocks";
import { replyArrived, streamStalled, tapFinished } from "../reply";
import { ApprovalCard, type Approval } from "../components/ApprovalCard";
import { ChartBlock, ChartPending } from "../components/ChartBlock";
import { Diagram } from "../components/Diagram";
import { ImageStrip, SafeImage } from "../components/ImageStrip";
import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { userLocale } from "../locale";
import { withMedia, type Media } from "../media";
import { MediaList } from "../components/MediaList";
import { PrivateReply } from "../privateReply";
import { somethingPlaying } from "../playing";
import { autoplayFor } from "../reminders";
import { FOCUS_COMPOSER } from "../components/ReminderCurtain";
import { useProfile } from "../profile";
import { MicWave } from "../components/MicWave";
import { composerWith, phoneSpeech, pickMode, startDictation } from "../dictation";

// key and sid: the name the server gave a reply (its ADK event id) and the session it is in; its saved ticks hang off them.
type Msg = { id: number; key?: string; sid?: string; role: "user" | "odie" | "approval"; text: string; tools: Tool[]; error?: string; awaiting?: boolean; ts?: number; live?: boolean; approval?: Approval; images?: string[]; asked?: string; media?: Media[]; autoplay?: string; private?: boolean; usage?: ReplyUsage };  // private: its chat read a signed-in page; usage: the reply's own token counts
type Pending = { id: string; url: string; w: number; h: number };
let nextId = 1;
const EASE = [0.2, 0.8, 0.2, 1] as const;
const GAP_FOR_DIVIDER = 20 * 60;   // seconds between messages before a time divider appears

function fmtTime(ts?: number) { return ts ? new Date(ts * 1000).toLocaleTimeString(userLocale(), { hour: "numeric", minute: "2-digit" }) : ""; }


const ROLLOVER = "(Continuing from earlier today.)";  // older chats only: Odie no longer starts over, it trims
const NEW_CHAT = "(New chat.)";  // a segment the user started by hand: Odie sees nothing above it

/** After "/new" the screen starts clean: only what comes after the last new-chat marker (earlier chats are in Threads). */
export function afterLastNewChat<T extends { role: string; text: string }>(items: T[]): { items: T[]; cut: boolean } {
  let i = -1;
  items.forEach((m, k) => { if (m.role === "odie" && m.text === NEW_CHAT) i = k; });
  return i < 0 ? { items, cut: false } : { items: items.slice(i + 1), cut: true };
}

function Icon({ d, size = 16, children }: { d?: string; size?: number; children?: ReactNode }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">{d ? <path d={d} /> : children}</svg>;
}

const mdComponents: Components = {
  pre({ node, children }) {
    const child = Array.isArray(children) ? children[0] : children;
    const props = (child as { props?: { className?: string; children?: ReactNode } })?.props ?? {};
    const lang = (props.className ?? "").replace("language-", "");
    const code = String(props.children ?? "").replace(/\n$/, "");
    const shown = howChatShowsFence(lang, code);
    const offset = node?.position?.start.offset ?? 0;  // which fence of the reply this is, for saving its ticks
    if (shown.as === "blocks") return <Enlarge label="Blocks"><BlocksFence blocks={shown.blocks} source={code} offset={offset} /></Enlarge>;  // none drawable: "Couldn't draw this", readable as text
    if (shown.as === "broken") return <Blocks blocks={[]} source={code} />;  // finished but broken JSON: say so, never show it as code
    if (shown.as === "waiting") return <ChartPending />;  // still streaming in
    if (shown.as === "images") return <ImageStrip spec={shown.spec} />;
    if (shown.as === "chart") return <Enlarge label="Chart"><ChartBlock spec={shown.spec} /></Enlarge>;
    if (shown.as === "diagram") return <Enlarge label="Diagram"><Diagram code={code} /></Enlarge>;
    if (shown.as === "svg") return <SvgBlock svg={shown.svg} />;
    return <CodeBlock lang={lang} code={code} />;
  },
  table({ children }) { return <div className="table-wrap"><table>{children}</table></div>; },
  img({ src, alt }) { return typeof src === "string" && /^(https?:\/\/|\/api\/(photos|media)\/)/.test(src) ? <SafeImage src={src} alt={alt} className="my-2 max-w-full max-h-[320px] rounded-[16px] border border-line object-cover" /> : null; },
  a({ href, children }) { return <a href={href} target="_blank" rel="noreferrer">{children}</a>; },
  span: MarkdownSpan,  // :icon[…] in reply text (remarkInline marks them)
};

/** A finished reply drawn the way the chat draws one (Markdown, blocks, charts, photos), with nowhere to save ticks:
 *  for the #sample screen, which shows a saved conversation. */
export function ReplyText({ text }: { text: string }) {
  const shown = plainMath(tidyStrayBlocks(liftOneLineFences(text)));
  return (
    <ReplyPlace.Provider value={{ text: shown }}>
      <div className="glass rounded-[8px_26px_26px_26px] px-4 py-3.5 md @container"><ReactMarkdown remarkPlugins={[remarkGfm, remarkInline]} components={mdComponents}>{shown}</ReactMarkdown></div>
    </ReplyPlace.Provider>
  );
}

/** A streamed piece's reply name, when the server sent one: {key: "3f2b…", sid: "chat-2026-10-11"}; else nothing. */
function replyName(ev: ChatEvent): { key?: string; sid?: string } {
  const named = ev as { key?: unknown; session_id?: unknown };
  if (typeof named.key !== "string" || typeof named.session_id !== "string") return {};
  return { key: named.key, sid: named.session_id };
}

function SegmentDivider({ text, ts }: { text: string; ts?: number }) {
  // The day rolled into a fresh segment: Odie now works from this summary instead of everything above.
  const [open, setOpen] = useState(false);
  return (
    <div className="flex flex-col gap-2">
      <button onClick={() => setOpen((v) => !v)} className="min-h-11 flex items-center justify-center" aria-expanded={open}>
        <span className="self-center text-[12px] font-semibold text-muted px-3 py-1 rounded-full bg-well">Fresh start{ts ? ` · ${fmtTime(ts)}` : ""} · {open ? "hide summary" : "summary of earlier"}</span>
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.16 }} className="overflow-hidden">
            <div className="glass rounded-[18px] px-4 py-3 text-[14px] leading-5 text-muted">{text}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function NewChatDivider({ ts, name }: { ts?: number; name: string }) {
  return (
    <div className="flex justify-center min-h-11 items-center"><span className="self-center text-[12px] font-semibold text-muted px-3 py-1 rounded-full bg-well text-center">New chat{ts ? ` · ${fmtTime(ts)}` : ""} · {name} doesn't see anything above</span></div>
  );
}

function ContextRing({ used, limit }: { used: number; limit: number }) {
  // How full the conversation is, against the point where Odie sends older turns as words only.
  const pct = Math.min(100, Math.round((used / Math.max(1, limit)) * 100));
  const r = 7, c = 2 * Math.PI * r;
  return (
    <span className="flex items-center gap-1.5 text-[12px] tabular-nums">
      <svg width="18" height="18" viewBox="0 0 18 18" className="-rotate-90" aria-hidden="true">
        <circle cx="9" cy="9" r={r} fill="none" stroke="currentColor" strokeOpacity=".25" strokeWidth="2.5" />
        <circle cx="9" cy="9" r={r} fill="none" stroke={pct >= 80 ? "var(--t-warn)" : "var(--t-brand)"} strokeWidth="2.5" strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={c * (1 - pct / 100)} style={{ transition: "stroke-dashoffset .4s" }} />
      </svg>
      {pct}%
    </span>
  );
}

/** The question Today handed over in "#chat?q=…", or null. */
export function askedFromHash(hash: string): string | null {
  const m = hash.match(/^#chat\?q=(.+)$/);
  return m ? decodeURIComponent(m[1]) : null;
}

/** Composer height for its content, 1 to 5 lines; "" (natural height) while hidden, when there is nothing to measure. */
export function composerHeight(scrollHeight: number): string {
  return scrollHeight > 0 ? `${Math.min(scrollHeight, 22 * 5 + 4)}px` : "";
}

function TimeDivider({ ts }: { ts: number }) {
  const d = new Date(ts * 1000);
  const today = new Date().toDateString() === d.toDateString();
  return (
    <div className="flex justify-center"><span className="self-center text-[12px] font-semibold text-muted px-3 py-1 rounded-full bg-well">{today ? "Today" : d.toLocaleDateString(userLocale(), { day: "numeric", month: "short" })} · {fmtTime(ts)}</span></div>
  );
}

export function Chat({ orb, setOrb }: { orb: OrbState; setOrb: (s: OrbState) => void }) {
  // The count on Back to Today: what the background watch flagged that Today hasn't shown yet. Chat stays mounted, so it's
  // read again each time chat comes back into view.
  const [needYou, setNeedYou] = useState(0);
  useEffect(() => {
    const load = () => { if (location.hash.startsWith("#chat") || location.hash === "") getJSON<{ unseen?: number }>("/api/watch").then((w) => setNeedYou(w.unseen ?? 0)).catch(() => {}); };
    load();
    window.addEventListener("hashchange", load);
    return () => window.removeEventListener("hashchange", load);
  }, []);
  const you = useProfile()?.user_name ?? "";
  const caps = useCaps();
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [thinking, setThinkingState] = useState(() => {
    try { return localStorage.getItem("odie.think") !== "off"; } catch { return true; }
  });
  const setThinking = (on: boolean) => {
    setThinkingState(on);
    try { localStorage.setItem("odie.think", on ? "on" : "off"); } catch { /* private mode */ }
  };
  const [plusOpen, setPlusOpen] = useState(false);
  const [ctx, setCtx] = useState<{ used: number; limit: number } | null>(null);
  const [ctxNote, setCtxNote] = useState(false);
  const loadCtx = useCallback(() => { getJSON<{ used: number; limit: number }>("/api/chat/context").then(setCtx).catch(() => {}); }, []);
  const [speakingId, setSpeakingId] = useState<number | null>(null);
  const [preparingId, setPreparingId] = useState<number | null>(null);
  const stopRead = useRef<(() => void) | null>(null);
  const [listening, setListening] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [micNote, setMicNote] = useState("");  // why the mic couldn't write it down, shown under the box
  const micLevel = useRef(0);  // the voice's loudness right now, for the wave
  const [talking, setTalking] = useState(false);
  const { name } = usePersona();
  const stopDictate = useRef<(() => void) | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const field = useRef<HTMLTextAreaElement>(null);

  const [stopping, setStopping] = useState(false);
  useEffect(() => { if (!busy) setStopping(false); }, [busy]);  // eslint-disable-line react-hooks/exhaustive-deps
  const [thread, setThread] = useState<Thread | null>(null);  // null = today's chat
  const [threadsOpen, setThreadsOpen] = useState(false);
  // On a desktop Threads stays open beside the chat instead of sliding in (layout.ts); it reloads after each reply.
  const wide = useWide();
  const [threadsReload, setThreadsReload] = useState(0);
  const threadRef = useRef<Thread | null>(null);
  threadRef.current = thread;
  const historyUrl = (q: string) => (thread ? `/api/threads/${thread.id}/history?${q}` : `/api/history?date=${todayISO()}&${q}`);
  const [earlier, setEarlier] = useState(0);  // index of the first loaded history item; >0 means more exists
  const [loadingEarlier, setLoadingEarlier] = useState(false);
  const [atBottom, setAtBottom] = useState(true);
  const [unseen, setUnseen] = useState(false);
  const mainRef = useRef<HTMLElement>(null);
  type H = { items: { key?: string; sid?: string; role: "user" | "odie" | "approval"; text: string; tools: string[]; ts?: number; images?: string[]; approval?: Approval; media?: Media[]; private?: boolean; usage?: ReplyUsage }[]; total: number; start: number };
  const toMsgs = (items: H["items"]): Msg[] => items.filter((m) => m.text || m.tools.length || m.images?.length || m.approval || m.media?.length).map((m) => ({ id: nextId++, key: m.key, sid: m.sid, role: m.role, text: m.text, ts: m.ts, images: m.images, approval: m.approval, media: m.media, private: m.private, usage: m.usage, tools: m.tools.map((n) => ({ name: n, done: true })) }));
  const [pending, setPending] = useState<Pending[]>([]);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  async function onPick(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []);
    e.target.value = "";
    if (!files.length) return;
    setUploading(true);
    try {
      for (const f of files.slice(0, 4)) {
        const fd = new FormData(); fd.append("file", f);
        const r = await fetch("/api/upload", { method: "POST", body: fd });
        if (r.ok) { const j = (await r.json()) as Pending; setPending((p) => [...p, j]); }
      }
    } finally { setUploading(false); }
  }

  // While history is swapped in (a return from the background, a reconnect), the list briefly shrinks and the browser
  // jumps to the top: ignore those scroll events, and come back to the latest message if that's where the user was.
  const atBottomRef = useRef(true);
  const streamAbort = useRef<AbortController | null>(null);  // the answer being streamed, if any
  const lastEventAt = useRef(0);
  const settling = useRef(false);
  const toLatest = () => requestAnimationFrame(() => { bottom.current?.scrollIntoView(); setAtBottom(true); atBottomRef.current = true; });
  const loadHistory = useCallback(async () => {
    // Last 30 messages first (fast on a phone), then pending approvals appended once, so neither fetch can wipe the other.
    const wasAtBottom = atBottomRef.current;
    settling.current = true;
    try {
      const h = await getJSON<H>(historyUrl("limit=30"));
      const fresh = afterLastNewChat(h.items);
      setEarlier(fresh.cut ? 0 : h.start);  // nothing above a "/new" is shown here
      const base: Msg[] = toMsgs(fresh.items);
      let waiting: Approval[] = [];
      try { waiting = await getJSON<Approval[]>("/api/approvals"); } catch { /* fine */ }
      const shown = new Set(base.map((m) => m.approval?.id).filter(Boolean));  // history already holds today's cards in place
      const extra = waiting.filter((a) => !shown.has(a.id));
      setMsgs([...base, ...extra.map((a) => ({ id: nextId++, role: "approval" as const, text: "", tools: [], approval: a }))]);
      if (waiting.length) setOrb("approval");
      if (wasAtBottom) toLatest();
    } catch { /* offline: keep what we have */ }
    finally { window.setTimeout(() => { settling.current = false; }, 600); }
  }, [setOrb, thread]);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { void loadHistory(); loadCtx(); }, [loadHistory, loadCtx]);

  async function loadEarlier() {
    if (loadingEarlier || earlier <= 0) return;
    setLoadingEarlier(true);
    try {
      const h = await getJSON<H>(historyUrl(`limit=30&before=${earlier}`));
      const el = mainRef.current; const h0 = el?.scrollHeight ?? 0;
      const fresh = afterLastNewChat(h.items);
      setEarlier(fresh.cut ? 0 : h.start);
      setMsgs((m) => [...toMsgs(fresh.items), ...m]);
      requestAnimationFrame(() => { if (el) el.scrollTop += el.scrollHeight - h0; });  // keep the viewport where it was
    } catch { /* ignore */ } finally { setLoadingEarlier(false); }
  }
  function onScroll() {
    const el = mainRef.current; if (!el || settling.current) return;
    const near = el.scrollHeight - el.scrollTop - el.clientHeight < 160;
    setAtBottom(near);
    atBottomRef.current = near;
    if (near) setUnseen(false);
    if (el.scrollTop < 200 && earlier > 0) void loadEarlier();
  }
  function jumpToLatest() { bottom.current?.scrollIntoView({ behavior: "smooth" }); setUnseen(false); }
  useEffect(() => { if (atBottom) bottom.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs, atBottom]);
  useEffect(() => {  // back on screen: the latest message, if that's where the user left off; a hung stream is dropped
    const onVisible = () => {
      if (document.visibilityState !== "visible") return;
      if (atBottomRef.current) toLatest();
      // iOS can leave a suspended answer stream hanging; give it a moment to wake, then fetch the saved answer instead.
      window.setTimeout(() => { if (streamStalled(!!streamAbort.current, lastEventAt.current, Date.now())) streamAbort.current?.abort(); }, 1500);
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const onReselect = (e: Event) => { if ((e as CustomEvent).detail === "chat") jumpToLatest(); };
    window.addEventListener("odie:tab-reselect", onReselect);
    return () => window.removeEventListener("odie:tab-reselect", onReselect);
  }, []);
  const grow = useCallback(() => {  // autogrow the composer, 1 to 5 lines
    const el = field.current; if (!el) return;
    el.style.height = "0px";
    el.style.height = composerHeight(el.scrollHeight);
  }, []);
  useEffect(grow, [input, grow]);
  useEffect(() => {
    // Chat mounts hidden behind Today: measure the composer and show the latest message when it opens.
    const onHash = () => { if (location.hash.startsWith("#chat")) requestAnimationFrame(() => { grow(); bottom.current?.scrollIntoView(); }); };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [grow]);

  // After Act on a reminder's curtain: the chat is open and the cursor goes to the composer.
  useEffect(() => {
    const focus = () => field.current?.focus();
    window.addEventListener(FOCUS_COMPOSER, focus);
    return () => window.removeEventListener(FOCUS_COMPOSER, focus);
  }, []);

  useLive(useCallback((e: any) => {
    if (e.type === "message" && e.text !== NEW_CHAT && belongsHere(e.session_id, threadRef.current?.id ?? null, todayISO())) {
      // A reply after a tap is her answer, not a reminder: show it like any other reply.
      // A reply after a tap replaces the "still working" row that waitForTap put up.
      const autoplay = autoplayFor(e, document.visibilityState === "visible", somethingPlaying()) ?? undefined;  // a spoken reminder
      setMsgs((m) => [...(e.kind === "reply" ? m.filter((x) => !x.awaiting) : m), { id: nextId++, role: "odie", text: e.text, tools: [], ts: e.ts, live: e.kind !== "reply", media: e.media, autoplay, private: !!e.private }]);
      setUnseen(true);
    }
    if (e.type === "google" && e.status === "connected") window.dispatchEvent(new Event("odie:google-connected"));
    if (e.type === "approval" && e.status === "pending") setMsgs((m) => m.some((x) => x.approval?.id === e.id) ? m : [...m, { id: nextId++, role: "approval", text: "", tools: [], ts: Date.now() / 1000, approval: e as Approval }]);
    if ((e.type === "approval" && e.status !== "pending") || e.type === "approval_done") setMsgs((m) => m.map((x) => x.approval?.id === e.id ? { ...x, approval: { ...x.approval!, status: e.status ?? x.approval!.status, result_text: e.text ?? x.approval!.result_text } } : x));
  }, []), useCallback(() => { if (!busy) loadHistory(); }, [busy, loadHistory]));

  const tapTimers = useRef<number[]>([]);
  useEffect(() => () => tapTimers.current.forEach((t) => window.clearInterval(t)), []);
  /** After Approve: show that Odie is on it, and fetch the answer once the card says the turn finished. */
  function waitForTap(id: number) {
    setMsgs((m) => [...m, { id: nextId++, role: "odie", text: "", tools: [], ts: Date.now() / 1000, awaiting: true }]);
    let tries = 0;
    const t = window.setInterval(async () => {
      tries += 1;
      try {
        if (tapFinished(await getJSON<Approval>(`/api/approvals/${id}`))) { window.clearInterval(t); await loadHistory(); return; }
      } catch { /* offline for now */ }
      if (tries >= 200) { window.clearInterval(t); setMsgs((m) => m.filter((x) => !x.awaiting)); }
    }, 3000);
    tapTimers.current.push(t);
  }

  const waitTimer = useRef<number | null>(null);
  function waitForReply(sentAt: number) {
    let tries = 0;
    const check = async () => {
      tries += 1;
      try {
        const h = await getJSON<H>(historyUrl("limit=2"));
        if (replyArrived(h.items, sentAt)) { stop(); await loadHistory(); return; }
      } catch { /* still offline */ }
      if (tries >= 100) { stop(); setMsgs((m) => m.map((x) => (x.awaiting ? { ...x, awaiting: false, error: "connection dropped" } : x))); }
    };
    const onVisible = () => { if (document.visibilityState === "visible") void check(); };
    const stop = () => {
      if (waitTimer.current) window.clearInterval(waitTimer.current);
      waitTimer.current = null;
      document.removeEventListener("visibilitychange", onVisible);
    };
    stop();
    document.addEventListener("visibilitychange", onVisible);
    waitTimer.current = window.setInterval(() => void check(), 3000);
    void check();
  }

  async function newChat() {
    if (busy) return;
    setPlusOpen(false); setInput("");
    setThread(null);
    try { await postJSON("/api/chat/new", {}); } catch { return; }
    await loadHistory();
    loadCtx();
    setThreadsReload((n) => n + 1);
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }

  async function send(text: string) {
    const t = text.trim() || (pending.length ? "What do you see in this?" : "");
    if (!t || busy) return;
    if (/^\/(clear|new)$/i.test(t)) { void newChat(); return; }
    if (stopDictate.current) { stopDictate.current(); stopDictate.current = null; setListening(false); }
    const imgs = pending.map((p) => p.id);
    setInput((cur) => (cur.trim() === text.trim() ? "" : cur)); setPending([]); setBusy(true); setOrb("thinking");  // a tapped button keeps the draft
    const now = Date.now() / 1000;
    const replyId = nextId + 1;
    setMsgs((m) => [...m, { id: nextId++, role: "user", text: t, tools: [], ts: now, images: imgs }, { id: nextId++, role: "odie", text: "", tools: [], ts: now, asked: t }]);
    // Patch the streaming reply by id: a live Odie message (reminder) may be appended while tokens arrive.
    const patch = (f: (last: Msg) => Msg) => setMsgs((m) => m.map((x) => (x.id === replyId ? f(x) : x)));
    let streamed = "";
    let askedApproval = false;
    let ended = false;  // the server said done or error; otherwise the stream was cut (app backgrounded)
    const settle = () => patch((l) => ({ ...l, tools: l.tools.map((x) => ({ ...x, done: true })), ts: Date.now() / 1000 }));
    const ac = new AbortController();
    streamAbort.current = ac;
    lastEventAt.current = Date.now();
    try {
      for await (const ev of streamChat(t, thinking, imgs, thread?.id, ac.signal)) {
        lastEventAt.current = Date.now();
        if (ev.type === "tool_start") patch((l) => ({ ...l, tools: [...l.tools, { name: String(ev.tool), done: false }] }));
        else if (ev.type === "tool_done") patch((l) => { const i = l.tools.findIndex((x) => x.name === ev.tool && !x.done); if (i < 0) return l; const tools = [...l.tools]; tools[i] = { ...tools[i], done: true }; return { ...l, tools }; });
        else if (ev.type === "media") setMsgs((m) => withMedia(m, (ev as unknown as { media: Media }).media, (x) => x.id === replyId));
        else if (ev.type === "private") patch((l) => ({ ...l, private: true }));  // web images in it wait for a tap
        else if (ev.type === "token") { streamed += String(ev.text); patch((l) => ({ ...l, text: streamed, ...replyName(ev) })); }
        else if (ev.type === "text") {
          streamed = String(ev.text);
          const usage = (ev as { usage?: ReplyUsage }).usage;  // the finished reply's counts, when the provider gave them
          patch((l) => ({ ...l, text: streamed, ...replyName(ev), ...(usage ? { usage } : {}) }));
        }
        else if (ev.type === "approval") { askedApproval = true; settle(); setMsgs((m) => m.some((x) => x.approval?.id === (ev as unknown as Approval).id) ? m : [...m, { id: nextId++, role: "approval", text: "", tools: [], ts: Date.now() / 1000, approval: ev as unknown as Approval }]); }
        else if (ev.type === "error") { ended = true; patch((l) => ({ ...l, error: String(ev.message) })); settle(); }
        else if (ev.type === "done") { ended = true; settle(); }
      }
    } catch { /* cut mid-stream, or dropped because it hung while the app was away: handled below */ }
    streamAbort.current = null;
    if (!ended) {
      // The server keeps working when the connection drops; wait for the saved answer instead of failing.
      patch((l) => ({ ...l, awaiting: true }));
      waitForReply(now);
    }
    setBusy(false); setOrb(askedApproval ? "approval" : "idle");
    loadCtx();
    setThreadsReload((n) => n + 1);
  }

  // A line the app sends for the user (odie:send), as if typed: "I'm signed in to amazon.in." after the live view's
  // Done. It waits for a reply still being written.
  const [queued, setQueued] = useState<string[]>([]);
  useEffect(() => {
    const on = (e: Event) => { const t = (e as CustomEvent).detail; if (typeof t === "string" && t.trim()) setQueued((q) => [...q, t]); };
    window.addEventListener("odie:send", on);
    return () => window.removeEventListener("odie:send", on);
  }, []);
  useEffect(() => {
    if (busy || queued.length === 0) return;
    const [next, ...rest] = queued;
    setQueued(rest);
    void send(next);
  }, [busy, queued]);  // eslint-disable-line react-hooks/exhaustive-deps

  // Today's tiles and threads open Chat with a question (#chat?q=...): it waits in the composer for the user to send.
  useEffect(() => {
    const take = () => {
      const q = askedFromHash(location.hash);
      if (q === null) return;
      history.replaceState(null, "", "#chat");
      setInput(q);
      requestAnimationFrame(() => { const f = field.current; if (f) { f.focus(); f.setSelectionRange(q.length, q.length); } });
    };
    take();
    window.addEventListener("hashchange", take);
    return () => window.removeEventListener("hashchange", take);
  }, []);

  function retry(m: Msg) {
    if (!m.asked) return;
    setMsgs((all) => all.filter((x) => x.id !== m.id && !(x.role === "user" && x.text === m.asked && x.id === m.id - 1)));
    void send(m.asked);
  }

  async function toggleMic() {
    // Tap to talk, tap again to stop. With an OpenAI key the words appear as you speak; without one, the phone's own
    // dictation; neither: a note says what's missing. The text so far is kept, the dictated words go after it.
    if (stopDictate.current) { stopDictate.current(); stopDictate.current = null; return; }
    setMicNote("");
    const base = input.trim();
    // What the mic last put in the composer. Once the composer holds something else (sent, cleared, typed over),
    // composerWith drops the words that still arrive, so an old phrase can't come back.
    let written = input;
    const stop = await startDictation(pickMode({ dictation: has(caps, "dictation"), phoneSpeech: phoneSpeech() }), {
      onText: (words) => setInput((composer) => {
        const next = composerWith({ composer, written, base, words });
        if (next === null) return composer;
        written = next;
        return next;
      }),
      onLevel: (l) => { micLevel.current = l; },
      onError: setMicNote,
      onState: (s) => {
        setListening(s === "recording"); setTranscribing(s === "transcribing"); setConnecting(s === "connecting");
        setOrb(s === "recording" ? "listening" : "idle");
        if (s === "idle") stopDictate.current = null;
      },
    });
    if (!stop) { setMicNote((n) => n || "I can't use the microphone here. Allow it in Settings for this app."); return; }
    stopDictate.current = stop;
  }

  // The user typing in the composer (or clearing it with the keyboard) while the mic listens: their text wins, and the
  // mic stops, so the wave doesn't keep going over words it won't write.
  function takeOverComposer(text: string) {
    setInput(text);
    if (stopDictate.current) { stopDictate.current(); stopDictate.current = null; }
  }

  function say(m: Msg) {
    if (speakingId === m.id || preparingId === m.id) { stopRead.current?.(); stopSpeaking(); setSpeakingId(null); setPreparingId(null); setOrb("idle"); return; }
    stopRead.current?.();
    stopRead.current = speak(m.text, () => { setPreparingId(null); setSpeakingId(m.id); setOrb("speaking"); }, () => { setPreparingId(null); setSpeakingId(null); setOrb("idle"); },
      () => setPreparingId(m.id));
  }

  const [refreshing, setRefreshing] = useState(false);
  function refreshApp() {
    // A home-screen app has no browser reload button: reload the whole page (fresh history, approvals and any new build).
    setRefreshing(true);
    setTimeout(() => window.location.reload(), 150);
  }

  const ctxKnown = !!ctx && ctx.limit > 0;  // no model yet (or it can't say its size): no ring, never "0k of 0k"
  const ctxText = ctxKnown ? `About ${Math.round(ctx.used / 1000)}k of ${Math.round(ctx.limit / 1000)}k · older turns trimmed at ${Math.round(ctx.limit / 1000)}k` : "";
  const status = ctxNote && ctxText ? ctxText : busy ? (stopping ? "Stopping…" : "Working on it") : orb === "listening" ? "Listening" : orb === "speaking" ? "Speaking" : orb === "approval" ? "Waiting for your tap" : "Here";
  const hasDraft = input.trim().length > 0 || pending.length > 0;
  let micPlaceholder = `Ask ${name} anything`;
  if (connecting) micPlaceholder = "Connecting…";
  if (listening) micPlaceholder = "Listening… tap the mic to finish";
  if (transcribing) micPlaceholder = "Writing it down…";
  const lastOdie = [...msgs].reverse().find((m) => m.role === "odie");

  return (
    <div className="flex h-full">
      {wide && <ThreadsSidebar current={thread?.id ?? null} onOpen={setThread} onNewChat={() => void newChat()} reload={threadsReload} />}
      <div className="relative flex flex-col h-full flex-1 min-w-0">
        <AnimatePresence>{talking && <TalkMode onClose={() => setTalking(false)} />}</AnimatePresence>
        <header className="chat-col sticky top-0 z-10 grid grid-cols-[auto_1fr_auto] items-center gap-2.5 px-[18px] pb-4 safe-top bg-overlay backdrop-blur-xl backdrop-saturate-150 [mask-image:linear-gradient(180deg,#000_82%,transparent)]">
          {/* On a desktop the rail has Today; an empty span holds the back button's place in the header grid. */}
          {wide ? <span /> : (
            <a href="#today" aria-label={`Back to Today${needYou ? `, ${needYou} need you` : ""}`} className="pill w-11 px-0 relative">
              <Glyph name="back" />
              {badge(needYou) && <span className="absolute -top-1 -right-1 min-w-[18px] h-[18px] px-1 rounded-full bg-ember text-on-ember text-[11px] font-bold grid place-items-center">{badge(needYou)}</span>}
            </a>
          )}
          <div className="flex items-center justify-center gap-2.5 min-w-0">
            <span className="relative shrink-0">
              <Avatar size={40} state={orb} />
              <i className={`absolute right-0 bottom-0 w-3 h-3 rounded-full border-2 border-[var(--t-ground)] ${busy || orb === "approval" ? "bg-gold" : "bg-good"}`} aria-hidden="true" />
            </span>
            <div className="flex flex-col items-start leading-tight min-w-0">
            <b className="text-[17px] font-bold truncate max-w-full">{name}</b>
            <AnimatePresence mode="wait" initial={false}>
              <motion.span key={status} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.16 }}
                className="text-[12.5px] text-muted inline-flex items-center gap-1.5 whitespace-nowrap max-w-full truncate">
                {status}
              </motion.span>
            </AnimatePresence>
            </div>
          </div>
          <div className="flex items-center gap-1.5">
            {!wide && <button onClick={() => setThreadsOpen(true)} aria-label="Threads" title="Threads" className="pill w-11 px-0"><Glyph name="menu" size={18} /></button>}
            {ctx && ctxKnown && !thread && (
              <button onClick={() => { setCtxNote(true); setTimeout(() => setCtxNote(false), 4000); }} aria-label={`Conversation ${ctxText}`} title={ctxText}
                className="pill h-11 px-2.5 text-[12px] font-bold"><ContextRing used={ctx.used} limit={ctx.limit} /></button>
            )}
            <button onClick={refreshApp} aria-label="Refresh" title="Refresh" className="pill w-11 px-0">
              <span className={`flex ${refreshing ? "animate-spin" : ""}`}><Glyph name="refresh" size={17} /></span>
            </button>
          </div>
        </header>
        {thread && (
          <div className="chat-col-edge mx-[18px] -mt-2 mb-1 flex items-center gap-2 px-3 py-2 rounded-[18px] glass">
            <button onClick={() => setThread(null)} className="text-[13px] font-semibold text-ember-text shrink-0">‹ Today</button>
            <button onClick={() => { const t = prompt("Name this thread", thread.title); if (t !== null) void postJSON(`/api/threads/${thread.id}/rename`, { title: t }).then(() => setThread({ ...thread, title: t.trim() || thread.title })); }}
              className="flex-1 min-w-0 text-left text-[14px] font-semibold truncate" title="Rename">{thread.title}</button>
            <button aria-label={thread.pinned ? "Unpin" : "Pin"} onClick={() => { const p = !thread.pinned; setThread({ ...thread, pinned: p }); void postJSON(`/api/threads/${thread.id}/pin`, { pinned: p }); }}
              className={`w-8 h-8 grid place-items-center shrink-0 ${thread.pinned ? "text-gold" : "text-dim"}`}><Star on={thread.pinned} /></button>
          </div>
        )}
        {!wide && <ThreadsSheet open={threadsOpen} current={thread?.id ?? null} onClose={() => setThreadsOpen(false)}
          onOpen={(t) => { setThreadsOpen(false); setThread(t); }} />}

        <div className="relative flex-1 min-h-0 flex flex-col">
          <main ref={mainRef} onScroll={onScroll} className="chat-col flex-1 overflow-y-auto no-scrollbar px-[18px] pb-3 flex flex-col">
            <ChatActions.Provider value={{ send: (t) => void send(t), busy, fill: (t) => {
              setInput(t);
              requestAnimationFrame(() => { const f = field.current; if (f) { f.focus(); f.setSelectionRange(t.length, t.length); } });
            } }}>
            <div className="fade-top" />
            {earlier > 0 && (
              <div className="self-center pt-1 pb-3">
                {loadingEarlier ? <span className="spinner inline-block" /> : (
                  <button onClick={loadEarlier} className="pill pill-flat h-8 text-[12px]">Earlier today · {earlier} more</button>
                )}
              </div>
            )}
            {msgs.length === 0 && (() => { const g = greetingParts(); return (
              <div className="min-h-[60dvh] flex flex-col items-center justify-center text-center pt-5">
                <Orb size={150} halo />
                <h2 className="text-[28px] font-bold tracking-[-0.02em] mt-7">{g.lead} <span className="serif text-[32px]">{g.accent}</span>{you ? `, ${you}` : ""}</h2>
                <p className="text-muted mt-1.5">What can I do for you?</p>
                <div className="self-start font-bold mt-8 mb-3">Try one of these</div>
                <div className="flex gap-3 overflow-x-auto no-scrollbar -mx-[18px] px-[18px] pb-2.5 w-[calc(100%+36px)]">
                  {ideasFor(caps, userCountry()).map((s) => (
                    <button key={s.q} onClick={() => { setInput(s.q); field.current?.focus(); }} className="glass shrink-0 w-[168px] text-left rounded-[24px] p-4 active:scale-[.97] transition-transform">
                      <Tile icon={s.icon} color={s.color} /><b className="block mt-3.5 text-[15px] leading-[1.3]">{s.q}</b><span className="text-[12.5px] text-muted">{s.from}</span>
                    </button>
                  ))}
                </div>
              </div>
            ); })()}
            <AnimatePresence initial={false}>
              {msgs.map((m, i) => {
                const prev = msgs[i - 1];
                const showTime = !!m.ts && (!prev?.ts || m.ts - prev.ts >= GAP_FOR_DIVIDER) && m.role !== "approval";
                const spacing = i === 0 ? "" : prev && prev.role === m.role ? "mt-2" : "mt-5";
                const streaming = busy && m.id === lastOdie?.id;
                const enter = { initial: { opacity: 0, y: 6 }, animate: { opacity: 1, y: 0 }, transition: { duration: 0.2, ease: EASE } };
                return (
                  <div key={m.id} className={spacing}>
                    {showTime && <div className="mb-3"><TimeDivider ts={m.ts!} /></div>}
                    {m.role === "approval" && m.approval ? (
                      <motion.div {...enter}><ApprovalCard a={m.approval} showResult={false} onDecided={(id, st) => { setOrb("idle"); if (st === "approved") waitForTap(id); }} /></motion.div>
                    ) : m.role === "odie" && m.text === NEW_CHAT ? (
                      <NewChatDivider ts={m.ts} name={name} />
                    ) : m.role === "odie" && m.text.startsWith(ROLLOVER) ? (
                      <SegmentDivider text={m.text.slice(ROLLOVER.length).trim()} ts={m.ts} />
                    ) : m.role === "user" ? (
                      <motion.div {...enter} className="ml-auto max-w-[80%] w-fit flex flex-col items-end gap-0.5">
                        {m.images && m.images.length > 0 && (
                          <div className="flex gap-0.5 justify-end flex-wrap mb-1">
                            {m.images.map((id) => <img key={id} src={`/api/uploads/${id}`} alt="" className="w-[140px] h-[140px] object-cover rounded-[18px]" />)}
                          </div>
                        )}
                        {m.text && <div className="bubble-me rounded-[24px] rounded-br-[8px] px-4 py-3 text-[15.5px] leading-[1.5] whitespace-pre-wrap break-words">{m.text}</div>}
                      </motion.div>
                    ) : (
                      <motion.div {...enter} className="flex flex-col gap-2.5">
                        <div className="flex items-center gap-2 text-[12.5px] text-muted font-semibold">
                          <Avatar size={36} /><span className="text-[13.5px]"><b className="text-ink-2 font-bold">{name}</b>{m.live ? " · reminder" : ""}{m.ts ? ` · ${fmtTime(m.ts)}` : ""}</span>
                        </div>
                        <Steps tools={m.tools} running={streaming} />
                        {m.awaiting && (
                          <div className="flex items-center gap-3"><Orb state="thinking" size={28} /><span className="text-[14px] font-semibold shimmer-text">Still working on it, the answer will appear here</span></div>
                        )}
                        {!m.text && !m.error && !m.awaiting && streaming && !m.tools.some((t) => !t.done) && (  /* a running step shows in the trace */
                          <div className="flex items-center gap-3"><Orb state="thinking" size={28} /><span className="text-[14px] font-semibold shimmer-text">{thinking ? "Thinking longer" : "Thinking"}</span></div>
                        )}
                        {m.text && (() => {
                          const shown = plainMath(tidyStrayBlocks(liftOneLineFences(splitConnect(m.text).text)));
                          return (
                            <PrivateReply.Provider value={!!m.private}>
                              <ReplyPlace.Provider value={{ sessionId: m.sid, messageKey: m.key, text: shown, streaming }}>
                                {/* @container: blocks in the reply size their grids to the bubble (wideColumns.ts), not the window. */}
                                <div className={`glass rounded-[8px_26px_26px_26px] px-4 py-3.5 md @container ${streaming ? "is-streaming" : ""}`}><ReactMarkdown remarkPlugins={[remarkGfm, remarkInline]} components={mdComponents}>{shown}</ReactMarkdown></div>
                              </ReplyPlace.Provider>
                            </PrivateReply.Provider>
                          );
                        })()}
                        {m.media && m.media.length > 0 && <MediaList items={m.media} live={streaming && m.id === lastOdie?.id} autoplay={m.autoplay} />}
                        {m.text && splitConnect(m.text).connect && <ConnectCard since={m.ts} />}
                        {m.error && (
                          <div className="flex items-center gap-3 bg-warn-tint rounded-[18px] px-3.5 py-2.5 text-[13px] leading-[18px] text-ink-2">
                            <span className="text-warn-ink"><Glyph name="x" size={16} /></span>
                            <span className="flex-1">{/network|fetch|connection|load failed/i.test(m.error) ? "Lost the connection." : `That didn't work: ${m.error}`}</span>
                            {m.asked && <button onClick={() => retry(m)} className="text-ember-text font-semibold min-h-8 px-1">Retry</button>}
                          </div>
                        )}
                        {m.text && !streaming && (
                          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.24 }} className="flex items-center gap-1 ml-1 text-muted">
                            <button onClick={() => say(m)} aria-label={speakingId === m.id ? "Stop speaking" : "Read aloud"} className="hit w-[34px] h-[34px] rounded-full grid place-items-center active:bg-well">
                              {speakingId === m.id ? <SpeakingBars /> : preparingId === m.id ? <span className="spinner" /> : <Glyph name="speaker" size={17} />}
                            </button>
                            <CopyButton text={m.text} />
                            {m.usage && <span className="ml-1 text-[12px] text-dim">{replyLine(m.usage)}</span>}
                          </motion.div>
                        )}
                      </motion.div>
                    )}
                  </div>
                );
              })}
            </AnimatePresence>
            <div ref={bottom} />
            <div className="fade-bottom" />
            </ChatActions.Provider>
          </main>
          <AnimatePresence>
            {!atBottom && (
              <motion.button initial={{ scale: 0.8, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.8, opacity: 0 }} transition={{ duration: 0.16 }}
                onClick={jumpToLatest} aria-label="Jump to latest"
                className="pill absolute right-5 bottom-3 w-10 h-10 px-0">
                <Icon d="M12 5v14M6 13l6 6 6-6" size={18} />
                {unseen && <span className="absolute top-0.5 right-0.5 w-2 h-2 rounded-full bg-brand" />}
              </motion.button>
            )}
          </AnimatePresence>
        </div>

        <form onSubmit={(e) => { e.preventDefault(); void send(input); }} className="chat-composer glass relative z-20 mx-3 mb-[max(env(safe-area-inset-bottom),12px)] rounded-[30px] pt-3 pb-2.5 pl-4 pr-2.5">
          <input ref={fileRef} type="file" accept="image/*" multiple onChange={onPick} className="hidden" />
          {(pending.length > 0 || uploading) && (
            <div className="flex gap-2 mb-2">
              {pending.map((p) => (
                <div key={p.id} className="relative">
                  <img src={p.url} alt="" className="w-14 h-14 object-cover rounded-[14px]" />
                  <button type="button" onClick={() => setPending((x) => x.filter((y) => y.id !== p.id))} aria-label="Remove photo"
                    className="hit absolute -top-1.5 -right-1.5 w-5 h-5 rounded-full bg-solid text-on-solid text-[12px] leading-none flex items-center justify-center">×</button>
                </div>
              ))}
              {uploading && <div className="w-14 h-14 rounded-[14px] bg-well flex items-center justify-center"><span className="spinner" /></div>}
            </div>
          )}
          {listening && <MicWave level={micLevel} />}
          <div className="flex items-end gap-1">
            <textarea id="composer" ref={field} rows={1} value={input} onChange={(e) => takeOverComposer(e.target.value)}
              // Enter is a new line (the user writes multi-line messages on the phone); send with the button, or ⌘/Ctrl+Enter.
              onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && !e.nativeEvent.isComposing) { e.preventDefault(); void send(input); } }}
              enterKeyHint="enter"
              onFocus={() => setTimeout(() => bottom.current?.scrollIntoView({ behavior: "smooth" }), 50)}
              placeholder={micPlaceholder}
              className={`flex-1 min-w-0 resize-none bg-transparent outline-none text-[16px] leading-[22px] py-1.5 max-h-[114px] ${listening || transcribing || connecting ? "placeholder:text-ember-text" : "placeholder:text-muted"}`}
              autoComplete="off" />
            {input && !listening && !transcribing && !connecting && (
              <button type="button" onClick={() => { setInput(""); field.current?.focus(); }} aria-label="Clear" className="shrink-0 w-9 h-9 rounded-full grid place-items-center text-muted active:bg-well">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
              </button>
            )}
            <button type="button" onClick={() => void toggleMic()} disabled={transcribing || connecting} aria-label={listening ? "Finish dictation" : "Dictate"}
              className={`shrink-0 w-9 h-9 rounded-full grid place-items-center ${listening ? "bg-solid text-on-solid" : "text-muted"}`}>
              {transcribing || connecting ? <span className="spinner" /> : listening ? <span className="w-3.5 h-3.5 rounded-[3px] bg-current" /> : <Glyph name="mic" size={19} />}
            </button>
          </div>
          {micNote && <div role="status" className="text-[12.5px] leading-[17px] text-warn mt-1">{micNote}</div>}
          <div className="flex items-center gap-2 mt-2">
            <div className="relative">
              <button type="button" onClick={() => setPlusOpen((v) => !v)} aria-label="More options" aria-expanded={plusOpen} className="pill pill-flat w-[42px] h-[42px] px-0">
                <motion.span animate={{ rotate: plusOpen ? 45 : 0 }} transition={{ duration: 0.16 }} className="flex"><Glyph name="plus" /></motion.span>
              </button>
              <AnimatePresence>
                {plusOpen && (
                  <>
                    <ToBody><div className="fixed inset-0 z-10" onClick={() => setPlusOpen(false)} /></ToBody>
                    <motion.div role="menu" initial={{ opacity: 0, y: 8, scale: 0.95 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 8, scale: 0.95 }} transition={{ duration: 0.16 }}
                      className="glass glass-solid absolute bottom-[52px] left-0 z-20 w-[250px] rounded-[24px] p-2 origin-bottom-left">
                      <button type="button" role="menuitem" onClick={() => void newChat()} disabled={busy}
                        className="w-full flex items-center gap-3 p-2 rounded-2xl text-[15px] font-semibold text-left active:bg-well disabled:opacity-50">
                        <Tile icon="spark" color="violet" small />New chat
                      </button>
                      <button type="button" role="menuitem" onClick={() => { setPlusOpen(false); fileRef.current?.click(); }}
                        className="w-full flex items-center gap-3 p-2 rounded-2xl text-[15px] font-semibold text-left active:bg-well">
                        <Tile icon="photo" color="pink" small />Add a photo
                      </button>
                      <button type="button" role="menuitemcheckbox" aria-checked={thinking} onClick={() => setThinking(!thinking)}
                        className="w-full flex items-center gap-3 p-2 rounded-2xl text-[15px] font-semibold text-left active:bg-well">
                        <Tile icon="brain" color="blue" small /><span className="flex-1">Think harder</span>
                        <span className={`relative w-11 h-[26px] rounded-full transition-colors ${thinking ? "bg-good" : "bg-dim"}`}>
                          <span className={`absolute top-[3px] w-5 h-5 rounded-full bg-white transition-all ${thinking ? "left-[21px]" : "left-[3px]"}`} />
                        </span>
                      </button>
                    </motion.div>
                  </>
                )}
              </AnimatePresence>
            </div>
            <span className="flex-1" />
            {/* Talk (a live voice conversation) is held back for now: the server never grants "talk", so this stays hidden. */}
            {has(caps, "talk") && (
              <button type="button" onClick={() => { stopSpeaking(); setTalking(true); }} aria-label={`Talk with ${name}`} className="pill pill-flat h-[42px]"><Glyph name="wave" size={18} /> Speak</button>
            )}
            {busy ? (
              // While Odie works, the send button is Stop: the turn ends at its next safe step.
              <button type="button" onClick={() => { setStopping(true); void postJSON("/api/chat/stop", thread ? { session_id: thread.id } : {}).catch(() => {}); }}
                disabled={stopping} aria-label="Stop"
                className="shrink-0 w-[42px] h-[42px] rounded-full grid place-items-center bg-solid text-on-solid disabled:opacity-50 transition-opacity">
                <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="5" width="14" height="14" rx="3" fill="currentColor" /></svg>
              </button>
            ) : (
              <button type="submit" disabled={!hasDraft} aria-label="Send"
                className="shrink-0 w-[42px] h-[42px] rounded-full grid place-items-center text-white bg-iris shadow-[0_10px_20px_-8px_#8a7dff] disabled:opacity-35 disabled:shadow-none transition-opacity">
                <Glyph name="up" size={20} stroke={2.4} />
              </button>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}
