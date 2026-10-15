import { AnimatePresence, motion } from "framer-motion";
import { WatchCard } from "../components/WatchCard";
import type { WatchCardData } from "../watch";
import { useCallback, useEffect, useState } from "react";
import { useLive } from "../live";
import { getJSON, postJSON, todayISO } from "../api";
import { Orb } from "../components/Orb";
import { Avatar } from "../components/Avatar";
import { Icon, Tile, type IconName, type TileColor } from "../components/Tile";
import type { Approval } from "../components/ApprovalCard";
import { greetingParts } from "../greeting";
import { dissolve } from "../dissolve";
import { InstallNudge } from "../components/InstallNudge";
import { NewsSection } from "../components/NewsSection";
import { InlineText } from "../blocks/InlineText";
import { avatarColour, initialOf } from "../blocks/rowAvatar";
import { TrackingSection } from "../components/TrackingSection";
import { UpNext } from "../components/UpNext";
import { busyDates, dayEvents, type UpItem } from "../upnext";
import { MoneyCard } from "../components/MoneyCard";
import { has, useCaps } from "../capabilities";
import { userLocale } from "../locale";
import { useProfile } from "../profile";

type Task = { id: number; title: string; kind: string; status: string; due_at: string | null; next_check_at: string | null; delivered_at?: string | null; source_kind?: string | null; detail?: string | null };  // detail: a mail thread's "from X" line, then its gist
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

/** How many threads the user closed today; 0 if the server can't say (older server, offline). */
/** Happening right now: started and not yet ended. All-day events never get the outline. */
export function isNowEvent(e: Ev, nowHM: string): boolean {
  const hm = (x: string) => x.padStart(5, "0");
  return !!e.end && hm(e.time) <= hm(nowHM) && hm(nowHM) < hm(e.end);
}

export async function closedTodayCount(fetcher: () => Promise<{ count: number }>): Promise<number> {
  try { return (await fetcher()).count ?? 0; } catch { return 0; }
}

export function taskTile(t: { source_kind?: string | null }): { icon: IconName; color: TileColor } {
  return t.source_kind === "ledger" ? { icon: "rupee", color: "green" } : t.source_kind === "mail" ? { icon: "mail", color: "blue" } : { icon: "bell", color: "violet" };
}

export type TaskRowView = {
  title: string;
  subtitle: string;  // block text: :badge[…] pills and **bold** draw as in a chat row (InlineText)
  lead: { kind: "initial"; letter: string; colour: string } | { kind: "tile"; icon: IconName; color: TileColor };
  run: string;       // what tapping the row asks the chat
};

const MAIL_TITLE = /^Reply to (.+?): (.*)$/;  // the title shape an inbox add-on gives its "reply to" tasks

/**
 * How a thread shows in To close, the way the chat's list rows look. Worked examples:
 *   mail "Reply to Priya Nair: Can we move our 1:1?", detail "from Priya…\nCould we move to Thursday?"
 *     -> title "Priya Nair · Can we move our 1:1?", a "P" avatar in Priya's colour, subtitle ":badge[Reply] Could we move
 *        to Thursday?", tap asks "Open the email from Priya Nair about Can we move our 1:1?"
 *   ledger "Pay the electricity bill", due 5 Jan   -> the rupee tile, ":badge[Due] Sun 5 Jan · from your messages"
 *   reminder "Call Ravi", due today 5 pm            -> the bell tile, "Due Today 5:00 pm"; once it has fired,
 *                                                      ":badge[Now]{warn} Due Today 5:00 pm"
 */
export function taskRow(t: Task): TaskRowView {
  const when = fmtWhen(t);
  const mail = t.source_kind === "mail" ? t.title.match(MAIL_TITLE) : null;
  if (mail) {
    const [, sender, subject] = mail;
    const gist = (t.detail ?? "").split("\n")[1] ?? "";
    return { title: `${sender} · ${subject}`, subtitle: `:badge[Reply] ${gist}`.trim(),
             lead: { kind: "initial", letter: initialOf(sender) ?? "?", colour: avatarColour(sender) },
             run: `Open the email from ${sender} about ${subject}` };
  }
  const lead = { kind: "tile" as const, ...taskTile(t) };
  const run = `Tell me about: ${t.title}`;
  if (t.source_kind === "ledger") {
    const day = when.replace(/^Due /, "");
    const parts = [day, "from your messages"].filter(Boolean).join(" · ");
    return { title: t.title, subtitle: when.startsWith("Due") ? `:badge[Due] ${parts}` : parts, lead, run };
  }
  const fired = !!t.delivered_at && !!when;
  return { title: t.title, subtitle: fired ? `:badge[Now]{warn} ${when}` : when, lead, run };
}

function isoDay(offset: number) { const d = new Date(); d.setDate(d.getDate() + offset); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; }

function fmtWhen(t: Task): string {
  const iso = t.due_at || t.next_check_at;
  if (!iso) return "";
  const d = new Date(iso.length <= 10 ? `${iso}T09:00` : iso);
  if (isNaN(d.getTime())) return iso;
  const day = iso.slice(0, 10) === todayISO() ? "Today" : iso.slice(0, 10) === isoDay(1) ? "Tomorrow" : d.toLocaleDateString(userLocale(), { weekday: "short", day: "numeric", month: "short" });
  const hasTime = iso.length > 10 && !/T00:00/.test(iso);
  return `${t.due_at ? "Due" : "Check"} ${day}${hasTime ? ` ${d.toLocaleTimeString(userLocale(), { hour: "numeric", minute: "2-digit" })}` : ""}`;
}

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

export function Today() {
  const you = useProfile()?.user_name ?? "";
  const caps = useCaps();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [up, setUp] = useState<{ items: UpItem[]; sources: Record<string, boolean> } | null>(null);
  const [upLoading, setUpLoading] = useState(true);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [closed, setClosed] = useState(0);
  const [watch, setWatch] = useState<WatchCardData | null>(null);
  const loadWatch = useCallback(() => {
    getJSON<WatchCardData>("/api/watch").then((w) => { setWatch(w); if (w.unseen) void postJSON("/api/watch/seen", {}).catch(() => {}); }).catch(() => {});
  }, []);
  useEffect(loadWatch, [loadWatch]);
  const loadApprovals = useCallback(() => { getJSON<Approval[]>("/api/approvals").then(setApprovals).catch(() => {}); }, []);
  const loadTasks = useCallback(() => {
    getJSON<Task[]>("/api/tasks").then(setTasks).catch(() => {});
    void closedTodayCount(() => getJSON<{ count: number }>("/api/tasks/closed_today")).then(setClosed);
  }, []);
  const loadUp = useCallback(() => {
    getJSON<{ items: UpItem[]; sources: Record<string, boolean> }>("/api/upcoming").then(setUp).catch(() => {}).finally(() => setUpLoading(false));
  }, []);
  useEffect(() => { loadTasks(); loadApprovals(); loadUp(); }, [loadTasks, loadApprovals, loadUp]);
  useLive(useCallback((e: any) => { if (e.type === "task") loadTasks(); if (e.type === "approval" || e.type === "approval_done") loadApprovals(); }, [loadTasks, loadApprovals]),
    useCallback(() => { loadTasks(); loadApprovals(); loadUp(); }, [loadTasks, loadApprovals, loadUp]));

  async function done(id: number) {
    const el = document.querySelector<HTMLElement>(`[data-task="${id}"]`);
    if (el) await dissolve(el);
    setTasks((t) => t.filter((x) => x.id !== id)); setClosed((c) => c + 1);
    try { await postJSON(`/api/tasks/${id}/done`, {}); } catch { loadTasks(); }
  }
  async function snooze(id: number) {
    const until = `${isoDay(1)}T09:00`;
    setTasks((t) => t.filter((x) => x.id !== id));
    try { await postJSON(`/api/tasks/${id}/snooze`, { until }); } catch { loadTasks(); }
  }

  const open = [...tasks.filter((t) => t.delivered_at), ...tasks.filter((t) => !t.delivered_at)];  // "Now" first
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

  return (
    <div className="h-full overflow-y-auto overflow-x-hidden no-scrollbar px-[18px] lg:px-8 safe-top pb-[110px] flex flex-col gap-[18px] [overflow-wrap:anywhere]">
      <div className="flex items-center justify-between rise">
        <div className="text-[13px] font-semibold text-muted whitespace-nowrap">{date}</div>
        <div className="flex items-center gap-2">
          <a href="#settings" aria-label="Settings" className="flex"><Avatar size={44} state={approvals.length ? "approval" : "idle"} /></a>
        </div>
      </div>

      <div className="rise" style={delay(0.05)}>
        <h1 className="text-[34px] leading-[1.12] font-bold tracking-[-0.025em]">{g.lead} <span className="serif text-[40px] text-ink-2">{g.accent}</span>{you ? <>,<br />{you}</> : null}</h1>
        <div className="mt-2.5 flex gap-2 flex-wrap">
          {comingUp > 0 && <span className="chip chip-soft">{comingUp} coming up this week</span>}
          {open.length > 0 && <span className="chip chip-warn">{open.length} to close</span>}
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
                className="flex items-center gap-3 px-3.5 py-3 rounded-[22px] bg-warn-tint text-warn-ink font-semibold text-[14.5px] border border-[rgba(255,178,63,.25)]">
                {/* Approvals live in Chat, next to what asked for them; Today only points there. */}
                <Tile icon="bell" color="yellow" small />
                <span className="flex-1">{approvals.length === 1 ? "1 thing waits" : `${approvals.length} things wait`} for your tap</span>
                <span aria-hidden="true">›</span>
              </motion.a>
            )}
          </AnimatePresence>

          {watch && <div className="rise" style={delay(0.08)}><WatchCard card={watch} onChange={loadWatch} /></div>}

          <div className="rise" style={delay(0.1)}><UpNext items={up?.items ?? null} loading={upLoading} /></div>

          <section className="glass rounded-[26px] p-[18px] rise order-last lg:order-none" style={delay(0.25)}>
            <div className="flex items-center justify-between gap-2 mb-1">
              <div className="text-[21px] font-bold tracking-[-0.015em]">To close</div>
              {closed + open.length > 0 && <ProgressChip closed={closed} total={closed + open.length} />}
            </div>
            <div className="text-[13.5px] text-muted mb-1.5">Dues, replies you owe and reminders. Tap the circle when it's done.</div>
            {open.length === 0 ? (
              <div className="flex flex-col items-center text-center pt-6 pb-4">
                <Orb size={64} halo />
                <span className="serif text-[26px] mt-2.5">All clear for today.</span>
                <div className="text-[13.5px] text-muted">I'll tell you when something new needs you.</div>
              </div>
            ) : (
              <AnimatePresence initial={false}>{open.map((t) => <TaskRow key={t.id} t={t} onDone={done} onSnooze={snooze} />)}</AnimatePresence>
            )}
          </section>
        </div>
        <div className="contents lg:flex lg:flex-col lg:gap-[18px]">
          <section className="glass rounded-[26px] px-2 pt-3.5 pb-3 grid grid-cols-7 text-center rise" style={delay(0.15)}>
            {weekDays().map((d) => {
              const dot = d.offset >= 0 && busy.has(isoDay(d.offset));
              return (
                <button key={d.key} onClick={() => ask(d.offset === 0 ? "What's on today?" : `What's on ${d.long}?`)}
                  className={`flex flex-col items-center gap-1.5 py-2 rounded-[18px] text-[12px] font-semibold ${d.offset === 0 ? "bg-solid text-on-solid shadow-[0_12px_24px_-12px_rgba(0,0,0,.45)]" : "text-muted"}`}>
                  {d.short}
                  <b className={`text-[18px] font-semibold ${d.offset === 0 ? "" : d.offset < 0 ? "text-dim" : "text-ink-2"}`}>{d.day}</b>
                  <i className={`w-[5px] h-[5px] rounded-full ${dot ? (d.offset === 0 ? "bg-[#ffd36b]" : "bg-brand") : ""}`} />
                </button>
              );
            })}
          </section>

          {cal !== undefined && has(caps, "calendar") && (
            <section className="glass rounded-[28px] p-1.5 rise" style={delay(0.2)}>
              {cal === null || !bands ? <div className="px-4 py-3.5 text-[14px] text-muted">Calendar not connected</div> : (
                <>
                  {cal.today.length === 0 ? (
                    <div className="band band-a rounded-[22px] px-3.5 py-3.5 mb-1.5 bg-[linear-gradient(160deg,rgba(186,214,255,.6),rgba(186,214,255,.18))] flex items-center justify-between">
                      <span><b className="text-[14px] text-ink-2">Today</b><span className="block text-[13px] text-muted">Nothing on the calendar. The day is yours.</span></span>
                      <span className="opacity-55"><Icon name="sun" size={18} /></span>
                    </div>
                  ) : (
                    <>
                      <Band name="Morning" icon="sunset" tone="m" events={bands.morning} nowHM={nowHM} />
                      <Band name="Afternoon" icon="sun" tone="a" events={bands.afternoon} nowHM={nowHM} />
                      <Band name="Evening" icon="moon" tone="e" events={bands.evening} nowHM={nowHM} />
                    </>
                  )}
                  <button onClick={() => ask("What's on my calendar tomorrow?")} className="w-full flex items-center gap-3 px-3 pt-2.5 pb-2 text-[14px] text-left">
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
    <div className={`band band-${tone} rounded-[22px] px-3.5 pt-3.5 pb-3 mb-1.5 ${BAND_BG[tone]}`}>
      <h4 className="text-[14px] font-bold flex justify-between items-center text-ink-2">{name}<span className="opacity-55"><Icon name={icon} size={16} /></span></h4>
      {events.length === 0 ? <div className="mt-2 text-[13px] text-muted">Free.</div> : events.map((e, i) => {
        const isNow = isNowEvent(e, nowHM);
        return (
          <button key={i} onClick={() => ask(`Tell me about ${e.title}`)} className="mt-2.5 flex gap-3 w-full text-left">
            <span className="w-11 shrink-0 text-[12.5px] font-semibold text-muted pt-3 tabular-nums">{e.time}</span>
            <span className={`flex-1 min-w-0 glass-solid rounded-2xl px-3.5 py-3 shadow-[0_8px_18px_-14px_rgba(60,40,20,.35)] text-[15px] font-semibold break-words ${isNow ? "outline-2 outline -outline-offset-2 outline-brand" : ""}`}>{e.title}</span>
          </button>
        );
      })}
    </div>
  );
}

function ProgressChip({ closed, total }: { closed: number; total: number }) {
  const c = 2 * Math.PI * 8, k = total ? closed / total : 0;
  return (
    <span className="inline-flex items-center gap-2 h-[34px] pl-1.5 pr-3 rounded-full bg-well text-[13px] font-bold whitespace-nowrap">
      <svg width="22" height="22" viewBox="0 0 22 22" className="-rotate-90" aria-hidden="true">
        <circle cx="11" cy="11" r="8" fill="none" stroke="var(--t-line-2)" strokeWidth="3" />
        <circle cx="11" cy="11" r="8" fill="none" stroke="var(--t-good)" strokeWidth="3" strokeLinecap="round" strokeDasharray={c} strokeDashoffset={c * (1 - k)}
          style={{ transition: "stroke-dashoffset .8s cubic-bezier(.34,1.56,.64,1)" }} />
      </svg>
      {closed} of {total} closed
    </span>
  );
}

export function TaskRow({ t, onDone, onSnooze }: { t: Task; onDone: (id: number) => void; onSnooze: (id: number) => void }) {
  const row = taskRow(t);
  const [ticked, setTicked] = useState(false);
  return (
    <motion.div layout exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.25, ease: EASE }} data-task={t.id}
      className="flex items-center gap-3 py-3 px-1 border-t border-line first:border-t-0">
      {row.lead.kind === "tile" ? <Tile icon={row.lead.icon} color={row.lead.color} /> : (
        <span className="w-9 h-9 shrink-0 rounded-full grid place-items-center text-white text-[15px] font-bold" style={{ background: row.lead.colour }} aria-hidden="true">{row.lead.letter}</span>
      )}
      <button onClick={() => ask(row.run)} className="flex-1 min-w-0 text-left">
        <div className="text-[15px] leading-[1.35] font-semibold break-words">{row.title}</div>
        {row.subtitle && <div className="text-[12.5px] leading-[17px] text-muted mt-0.5 line-clamp-2"><InlineText text={row.subtitle} /></div>}
      </button>
      <button onClick={() => onSnooze(t.id)} aria-label="Snooze until tomorrow 9am" className="hit w-[34px] h-[34px] shrink-0 rounded-full grid place-items-center text-dim"><Icon name="clock" size={18} /></button>
      <button onClick={() => { if (ticked) return; setTicked(true); setTimeout(() => onDone(t.id), 260); }} aria-label="Mark done"
        className={`hit w-[34px] h-[34px] shrink-0 rounded-full grid place-items-center transition-all duration-300 ${ticked ? "bg-good text-white scale-110" : "border-2 border-dashed border-dim text-transparent"}`}>
        <Icon name="check" size={18} stroke={2.6} />
      </button>
    </motion.div>
  );
}
