import { getPick, setPick, usePick } from "../pick";
import { usePickedPersona } from "../persona";
import { lightOf } from "../light";
import { OnIt } from "../components/OnIt";
import { asksToTurnOn, otherLine, pulseKicker, stillPicked, type JobDone, type LoopDone, type OnIt as OnItItem, type Other } from "../pulse";
import type { Proactive } from "../proactive";
import { AnimatePresence, motion } from "framer-motion";
import { NeedsYou } from "../components/NeedsYou";
import { footer, type WatchCardData } from "../watch";
import { busyWord, chatRunHash, opensSafely, type Need, type NeedAction, type WatchNote } from "../needs";
import { useCallback, useEffect, useState } from "react";
import { useLive } from "../live";
import { getJSON, postJSON, todayISO } from "../api";
import { Avatar } from "../components/Avatar";
import { Icon, Tile, type IconName } from "../components/Tile";
import type { Approval } from "../components/ApprovalCard";
import { greetingParts } from "../greeting";
import { InstallNudge } from "../components/InstallNudge";
import { NewsSection } from "../components/NewsSection";
import { TrackingSection } from "../components/TrackingSection";
import { UpNext } from "../components/UpNext";
import type { WatchClosedItem } from "../components/WatchClosed";
import { busyDates, dayEvents, type UpItem } from "../upnext";
import { MoneyCard } from "../components/MoneyCard";
import { has, useCaps } from "../capabilities";
import { userLocale } from "../locale";
import { useProfile } from "../profile";

type Ev = { time: string; end?: string; title: string };
const EASE = [0.2, 0.8, 0.2, 1] as const;

/** Today's and tomorrow's events from the calendar text the brief job stored (a calendar app's lines: id | when | title | guests). */
export function parseCalendar(raw: string | null | undefined, today: string, tomorrow: string): { today: Ev[]; tomorrow: Ev[] } | null {
  if (raw == null) return null;
  const out = { today: [] as Ev[], tomorrow: [] as Ev[] };
  let day = today;
  for (const line of raw.split("\n")) {
    const h = line.match(/^##\s+(\d{4}-\d{2}-\d{2})/);
    if (h) { day = h[1]; continue; }
    const cols = line.split("|").map((c) => c.trim());
    if (cols.length < 3) continue;
    const t = cols[1].match(/(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})/);
    const ev: Ev = /all day/i.test(cols[1]) || !t ? { time: "All day", title: cols[2] } : { time: t[1], end: t[2], title: cols[2] };
    if (day === today) out.today.push(ev); else if (day === tomorrow) out.tomorrow.push(ev);
  }
  return out;
}

/** The day in three bands, like light moving across a room: before noon, before five, after. All-day sits in the morning. */
export function bandsFor(events: Ev[]): { morning: Ev[]; afternoon: Ev[]; evening: Ev[] } {
  const out = { morning: [] as Ev[], afternoon: [] as Ev[], evening: [] as Ev[] };
  for (const e of events) {
    const h = /^\d{1,2}:\d{2}$/.test(e.time) ? parseInt(e.time, 10) : 0;
    (h >= 17 ? out.evening : h >= 12 ? out.afternoon : out.morning).push(e);
  }
  return out;
}

/** Happening right now: started and not yet ended. All-day events never get the outline. */
export function isNowEvent(e: Ev, nowHM: string): boolean {
  const hm = (x: string) => x.padStart(5, "0");
  return !!e.end && hm(e.time) <= hm(nowHM) && hm(nowHM) < hm(e.end);
}

function isoDay(offset: number) { const d = new Date(); d.setDate(d.getDate() + offset); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; }

function ask(q: string) { location.hash = `chat?q=${encodeURIComponent(q)}`; }

function weekDays() {
  const now = new Date();
  const mon = new Date(now); mon.setDate(now.getDate() - ((now.getDay() + 6) % 7));
  return Array.from({ length: 7 }, (_, i) => {
    const d = new Date(mon); d.setDate(mon.getDate() + i);
    const offset = Math.round((new Date(d.toDateString()).getTime() - new Date(now.toDateString()).getTime()) / 864e5);
    return { key: i, offset, day: d.getDate(), short: d.toLocaleDateString(userLocale(), { weekday: "short" }), long: d.toLocaleDateString(userLocale(), { weekday: "long" }) };
  });
}

type PulseGot = { items: Need[]; watch: Partial<WatchCardData>; notes?: WatchNote[]; on_it?: OnItItem[]; loops_done?: LoopDone[]; jobs_done?: JobDone[];
  others?: Other[]; proactive?: Proactive };

/** Pulse (it replaced Today): the picked one's own. Everyday Odie's keeps everything Today had, with what Odie is on
 *  and the others as a count; a personality's shows its own cards, what it's on and what it closed today. */
export function Today() {
  const you = useProfile()?.user_name ?? "";
  const caps = useCaps();
  const pick = usePick();
  const picked = usePickedPersona();
  const [onIt, setOnIt] = useState<OnItItem[]>([]);
  const [loopsDone, setLoopsDone] = useState<LoopDone[]>([]);
  const [jobsDone, setJobsDone] = useState<JobDone[]>([]);
  const [failed, setFailed] = useState("");  // a tap the server refused (Merge after new commits): its own words
  const [others, setOthers] = useState<Other[]>([]);
  const [proactive, setProactive] = useState<Proactive | null>(null);
  const [itsEvents, setItsEvents] = useState<{ id: string; title: string; start: string }[]>([]);
  const [up, setUp] = useState<{ items: UpItem[]; sources: Record<string, boolean> } | null>(null);
  const [upLoading, setUpLoading] = useState(true);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [watchClosed, setWatchClosed] = useState<WatchClosedItem[]>([]);
  const [needs, setNeeds] = useState<Need[] | null>(null);
  const [checked, setChecked] = useState("");  // under "Needs you": when the watch last checked, or what isn't working
  const [notes, setNotes] = useState<WatchNote[]>([]);  // what the watch told the user in the last day
  const loadNeeds = useCallback((): Promise<void> => {
    const askedFor = getPick();
    void postJSON("/api/watch/seen", {}).catch(() => {});
    return getJSON<PulseGot>("/api/needs_you").then((g) => {
      if (!stillPicked(askedFor, getPick())) return;  // the pick changed meanwhile: that one's cards never show here
      setNeeds(g.items);
      setNotes(g.notes ?? []);
      setOnIt(g.on_it ?? []);
      setLoopsDone(g.loops_done ?? []);
      setJobsDone(g.jobs_done ?? []);
      setOthers(g.others ?? []);
      setProactive(g.proactive ?? null);
      const w = g.watch;
      setItsEvents((w.events ?? []) as { id: string; title: string; start: string }[]);
      setChecked(w.off || (w.checked_at ? footer({ needs_you: [], events: [], unseen: 0, line: "", sources: {}, ...w } as WatchCardData, new Date()) : ""));
    }).catch(() => {});
  }, []);
  // Another pick: its own Pulse, never the last one's cards while it loads.
  useEffect(() => { setNeeds(null); setOnIt([]); setLoopsDone([]); setJobsDone([]); setFailed(""); setOthers([]); setProactive(null); setItsEvents([]); setWatchClosed([]); setApprovals([]); }, [pick]);
  // The picked one's cards waiting for a tap (a personality's Pulse shows its own, as its avatar does).
  const loadApprovals = useCallback(() => {
    const askedFor = getPick();
    getJSON<Approval[]>("/api/approvals").then((a) => { if (stillPicked(askedFor, getPick())) setApprovals(a); }).catch(() => {});
  }, []);
  const loadTasks = useCallback((): Promise<void> => {
    const askedFor = getPick();
    getJSON<WatchClosedItem[]>("/api/tasks/closed_by_watch").then((c) => { if (stillPicked(askedFor, getPick())) setWatchClosed(c); }).catch(() => {});
    return loadNeeds();
  }, [loadNeeds]);
  const loadUp = useCallback(() => {
    getJSON<{ items: UpItem[]; sources: Record<string, boolean> }>("/api/upcoming").then(setUp).catch(() => {}).finally(() => setUpLoading(false));
  }, []);
  useEffect(() => { loadTasks(); loadApprovals(); loadUp(); }, [loadTasks, loadApprovals, loadUp, pick]);
  useLive(useCallback((e: any) => { if (e.type === "task" || e.type === "message" || e.type === "pulse") loadTasks(); if (e.type === "approval" || e.type === "approval_done") loadApprovals(); }, [loadTasks, loadApprovals]),
    useCallback(() => { loadTasks(); loadApprovals(); loadUp(); }, [loadTasks, loadApprovals, loadUp]));

  async function reopen(id: number) {
    setWatchClosed((items) => items.filter((x) => x.id !== id));
    try { await postJSON(`/api/tasks/${id}/reopen`, {}); } finally { loadTasks(); }
  }
  // Split (a card's small menu): the lines he picked become a loop of their own; the list is read again after.
  async function splitLoop(id: number, eventIds: number[]): Promise<void> {
    setFailed("");
    try { await postJSON(`/api/loops/${id}/split`, { events: eventIds }); } catch (e) { setFailed(e instanceof Error ? e.message : String(e)); }
    await loadTasks();
  }
  async function reopenLoop(id: number) {
    setLoopsDone((items) => items.filter((x) => x.id !== id));
    try { await postJSON(`/api/loops/${id}/reopen`, {}); } finally { loadTasks(); }
  }
  // A card's button: chat sends its request; Done, Later and the like take their card away at once (harmless);
  // Merge, Use this, Allow and Retry leave it in place, busy (NeedsYou), until the server answers and the list is
  // re-read, so nothing slides up under the finger.
  async function act(need: Need, a: NeedAction): Promise<void> {
    if (a.action === "chat") { location.hash = chatRunHash(String(a.value)); return; }
    if (a.action === "open") {
      if (opensSafely(String(a.value))) window.open(String(a.value), "_blank", "noopener");
      return;
    }
    if (!busyWord(a.action)) setNeeds((items) => (items ?? []).filter((x) => x.ref !== need.ref));
    setFailed("");
    try {
      if (a.action === "dismiss") await postJSON("/api/watch/done", { ref: a.value });
      if (a.action === "done_task") await postJSON(`/api/tasks/${a.value}/done`, {});
      if (a.action === "snooze_task") await postJSON(`/api/tasks/${a.value}/snooze`, { until: `${isoDay(1)}T09:00` });
      if (a.action === "later") await postJSON("/api/needs_you/later", { ref: a.value });
      if (a.action === "loop_done") await postJSON(`/api/loops/${a.value}/done`, {});
      if (a.action === "job_retry") await postJSON(`/api/jobs/${a.value}/retry`, {});
      if (a.action === "job_allow") await postJSON(`/api/jobs/${a.value}/allow`, { hash: need.allow_hash ?? "" });
      if (a.action === "job_clear") await postJSON(`/api/jobs/${a.value}/clear`, {});
      if (a.action === "merge") await postJSON(`/api/loops/${a.value}/merge`, {});
      if (a.action === "recipe_use") await postJSON("/api/recipes/use", { repo: a.value });
      if (a.action === "recipe_no") await postJSON("/api/recipes/no", { repo: a.value });
    } catch (e) { setFailed(e instanceof Error ? e.message : String(e)); }
    await loadTasks();
  }
  // Stop keeps its row (OnIt shows "Stopping…") until the list is re-read.
  async function stopJob(id: string): Promise<void> {
    try { await postJSON(`/api/jobs/${id}/stop`, {}); } catch { /* it had ended */ }
    await loadTasks();
  }

  // The day bands and week dots read the same merged list as Up next (calendar, SMS, mail, tasks).
  const cal = !up ? undefined : up.sources.calendar === false && up.items.length === 0 ? null
    : { today: dayEvents(up.items, todayISO()), tomorrow: dayEvents(up.items, isoDay(1)) };
  const busy = busyDates(up?.items ?? []);
  const comingUp = (up?.items ?? []).filter((i) => i.date <= isoDay(6)).length;
  const date = new Date().toLocaleDateString(userLocale(), { weekday: "long", day: "numeric", month: "long" });
  const g = greetingParts();
  const bands = cal ? bandsFor(cal.today) : null;
  const nowHM = new Date().toTimeString().slice(0, 5);
  const delay = (s: number) => ({ animationDelay: `${s}s` });

  const needsYou = (
    <>
    {failed && <div role="alert" className="glass rounded-tile px-3.5 py-3 mb-2.5 text-ui text-warn-ink bg-warn-tint">{failed}</div>}
    <NeedsYou items={needs} footer={checked} closed={watchClosed} notes={notes} loopsDone={loopsDone} jobsDone={jobsDone}
      onAct={(n, a) => act(n, a)} onReopen={(id) => void reopen(id)} onReopenLoop={(id) => void reopenLoop(id)} onSplit={splitLoop}
      empty={pick && !proactive?.on ? "Nothing waiting. Its own reminders and cards show here." : undefined} />
    </>
  );
  if (pick) {
    return (
      <div className="h-full overflow-y-auto overflow-x-hidden no-scrollbar px-[18px] lg:px-8 safe-top pb-[110px] flex flex-col gap-[18px] [overflow-wrap:anywhere]">
        <div className="flex items-center justify-between rise">
          <div className="text-small font-semibold text-muted truncate">{pulseKicker(pick, date, picked.name)}</div>
          <a href="#settings" aria-label="Settings" className="flex"><Avatar size={44} state={approvals.length ? "approval" : "idle"} who={picked} light={lightOf(pick)} /></a>
        </div>
        <div className="rise" style={delay(0.05)}>
          <h1 className="text-[34px] leading-[1.12] font-bold tracking-[-0.025em]">{picked.name}'s <span className="serif text-[40px] text-ink-2">Pulse</span></h1>
          <div className="mt-2.5 flex gap-2 flex-wrap">
            {(needs?.length ?? 0) > 0 && <span className="chip chip-warn">{needs?.length} need you</span>}
            {onIt.length > 0 && <span className="chip chip-soft">{picked.name} is on {onIt.length}</span>}
          </div>
        </div>
        {asksToTurnOn(proactive) && (
          <a href="#settings" className="glass rounded-tile px-3.5 py-3 flex items-center gap-3 text-ui rise" style={delay(0.06)}>
            <Tile icon="spark" color="violet" small />
            <span className="flex-1 min-w-0">Turn on <b>Proactive intelligence</b> in Settings and {picked.name} checks {proactive?.apps.join(", ")} every 30 minutes.</span>
            <span className="text-dim" aria-hidden="true">›</span>
          </a>
        )}
        <div className="contents lg:grid lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)] lg:gap-6 lg:items-start">
          <div className="contents lg:flex lg:flex-col lg:gap-[18px]">
            <div className="rise" style={delay(0.08)}>{needsYou}</div>
          </div>
          <div className="contents lg:flex lg:flex-col lg:gap-[18px]">
            <div className="rise" style={delay(0.1)}><OnIt items={onIt} who={picked.name} onStop={(id) => stopJob(id)} /></div>
            {itsEvents.length > 0 && (
              <section className="glass rounded-card px-4 py-3 rise" style={delay(0.12)} aria-label="Coming up">
                <div className="text-ui font-bold text-ink-2 mb-1">Coming up</div>
                {itsEvents.slice(0, 6).map((e) => (
                  <div key={e.id} className="flex gap-3 py-1.5 text-ui"><span className="w-24 shrink-0 text-muted tabular-nums">{e.start.slice(5, 16).replace("T", " ")}</span><span className="flex-1 min-w-0 text-ink-2">{e.title}</span></div>
                ))}
              </section>
            )}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto overflow-x-hidden no-scrollbar px-[18px] lg:px-8 safe-top pb-[110px] flex flex-col gap-[18px] [overflow-wrap:anywhere]">
      <div className="flex items-center justify-between rise">
        <div className="text-small font-semibold text-muted whitespace-nowrap">{pulseKicker("", date, "Odie")}</div>
        <div className="flex items-center gap-2">
          <a href="#settings" aria-label="Settings" className="flex"><Avatar size={44} state={approvals.length ? "approval" : "idle"} /></a>
        </div>
      </div>

      <div className="rise" style={delay(0.05)}>
        <h1 className="text-[34px] leading-[1.12] font-bold tracking-[-0.025em]">{g.lead} <span className="serif text-[40px] text-ink-2">{g.accent}</span>{you ? <>,<br />{you}</> : null}</h1>
        <div className="mt-2.5 flex gap-2 flex-wrap">
          {comingUp > 0 && <span className="chip chip-soft">{comingUp} coming up this week</span>}
          {(needs?.length ?? 0) > 0 && <span className="chip chip-warn">{needs?.length} need you</span>}
          {/* The other personalities, as a count only; a tap opens that one's Pulse. */}
          {others.map((o) => (
            <button key={o.id} type="button" onClick={() => setPick(o.id)} className="chip chip-soft">{otherLine(o)}</button>
          ))}
        </div>
      </div>

      <InstallNudge />

      {/* A desktop shows two columns: what needs you on the left (approvals, the watch, up next, to close), the week,
          calendar, money, tracking and news on the right. On a phone and a tablet the two wrappers vanish (display:
          contents): one column as always, with To close moved back to the end (order-last). */}
      <div className="contents lg:grid lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)] lg:gap-6 lg:items-start">
        <div className="contents lg:flex lg:flex-col lg:gap-[18px]">
          <AnimatePresence initial={false}>
            {approvals.length > 0 && (
              <motion.a href="#chat" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.2, ease: EASE }}
                className="flex items-center gap-3 px-3.5 py-3 rounded-tile bg-warn-tint text-warn-ink font-semibold text-ui border border-[rgba(255,178,63,.25)]">
                {/* Approvals live in Chat, next to what asked for them; Today only points there. */}
                <Tile icon="bell" color="yellow" small />
                <span className="flex-1">{approvals.length === 1 ? "1 thing waits" : `${approvals.length} things wait`} for your tap</span>
                <span aria-hidden="true">›</span>
              </motion.a>
            )}
          </AnimatePresence>

          <div className="rise" style={delay(0.08)}>{needsYou}</div>

          <div className="rise" style={delay(0.09)}><OnIt items={onIt} who={picked.name} onStop={(id) => stopJob(id)} /></div>

          <div className="rise" style={delay(0.1)}><UpNext items={up?.items ?? null} loading={upLoading} /></div>

        </div>
        <div className="contents lg:flex lg:flex-col lg:gap-[18px]">
          <section className="glass rounded-card px-2 pt-3.5 pb-3 grid grid-cols-7 text-center rise" style={delay(0.15)}>
            {weekDays().map((d) => {
              const dot = d.offset >= 0 && busy.has(isoDay(d.offset));
              return (
                <button key={d.key} onClick={() => ask(d.offset === 0 ? "What's on today?" : `What's on ${d.long}?`)}
                  className={`flex flex-col items-center gap-1.5 py-2 rounded-tile text-caption font-semibold ${d.offset === 0 ? "bg-solid text-on-solid shadow-[0_12px_24px_-12px_rgba(0,0,0,.45)]" : "text-muted"}`}>
                  {d.short}
                  <b className={`text-title font-semibold ${d.offset === 0 ? "" : d.offset < 0 ? "text-dim" : "text-ink-2"}`}>{d.day}</b>
                  <i className={`w-[5px] h-[5px] rounded-full ${dot ? (d.offset === 0 ? "bg-[#ffd36b]" : "bg-brand") : ""}`} />
                </button>
              );
            })}
          </section>

          {cal !== undefined && has(caps, "calendar") && (
            <section className="glass rounded-card p-1.5 rise" style={delay(0.2)}>
              {cal === null || !bands ? <div className="px-4 py-3.5 text-ui text-muted">Calendar not connected</div> : (
                <>
                  {cal.today.length === 0 ? (
                    <div className="band band-a rounded-tile px-3.5 py-3.5 mb-1.5 bg-[linear-gradient(160deg,rgba(186,214,255,.6),rgba(186,214,255,.18))] flex items-center justify-between">
                      <span><b className="text-ui text-ink-2">Today</b><span className="block text-small text-muted">Nothing on the calendar. The day is yours.</span></span>
                      <span className="opacity-55"><Icon name="sun" size={18} /></span>
                    </div>
                  ) : (
                    <>
                      <Band name="Morning" icon="sunset" tone="m" events={bands.morning} nowHM={nowHM} />
                      <Band name="Afternoon" icon="sun" tone="a" events={bands.afternoon} nowHM={nowHM} />
                      <Band name="Evening" icon="moon" tone="e" events={bands.evening} nowHM={nowHM} />
                    </>
                  )}
                  <button onClick={() => ask("What's on my calendar tomorrow?")} className="w-full flex items-center gap-3 px-3 pt-2.5 pb-2 text-ui text-left">
                    <span className="text-muted"><Icon name="cal" size={18} /></span>
                    <span className="flex-1 min-w-0 text-ink-2"><b>Tomorrow</b> · {cal.tomorrow.length ? cal.tomorrow.map((e) => `${e.time} ${e.title}`).join(", ") : "Clear"}</span>
                    <span className="text-dim" aria-hidden="true">›</span>
                  </button>
                </>
              )}
            </section>
          )}

          {has(caps, "money") && <MoneyCard />}

          <TrackingSection />

          <NewsSection />
        </div>
      </div>
    </div>
  );
}

const BAND_BG = {
  m: "bg-[linear-gradient(160deg,rgba(178,232,200,.55),rgba(178,232,200,.18))]",
  a: "bg-[linear-gradient(160deg,rgba(186,214,255,.6),rgba(186,214,255,.18))]",
  e: "bg-[linear-gradient(160deg,rgba(214,200,255,.6),rgba(214,200,255,.18))]",
} as const;

function Band({ name, icon, tone, events, nowHM }: { name: string; icon: IconName; tone: keyof typeof BAND_BG; events: Ev[]; nowHM: string }) {
  return (
    <div className={`band band-${tone} rounded-tile px-3.5 pt-3.5 pb-3 mb-1.5 ${BAND_BG[tone]}`}>
      <h4 className="text-ui font-bold flex justify-between items-center text-ink-2">{name}<span className="opacity-55"><Icon name={icon} size={16} /></span></h4>
      {events.length === 0 ? <div className="mt-2 text-small text-muted">Free.</div> : events.map((e, i) => {
        const isNow = isNowEvent(e, nowHM);
        return (
          <button key={i} onClick={() => ask(`Tell me about ${e.title}`)} className="mt-2.5 flex gap-3 w-full text-left">
            <span className="w-11 shrink-0 text-small font-semibold text-muted pt-3 tabular-nums">{e.time}</span>
            <span className={`flex-1 min-w-0 glass-solid rounded-2xl px-3.5 py-3 shadow-[0_8px_18px_-14px_rgba(60,40,20,.35)] text-body font-semibold break-words ${isNow ? "outline-2 outline -outline-offset-2 outline-brand" : ""}`}>{e.title}</span>
          </button>
        );
      })}
    </div>
  );
}
