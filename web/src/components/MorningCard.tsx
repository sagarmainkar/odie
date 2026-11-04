import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { getJSON, todayISO } from "../api";
import { usePersona } from "../persona";
import {
  accentParts, isTodaysChat, keepAsking, madeAtTime, MORNING_ASK_EVERY_MS, weatherTitle,
  type MorningCard as Card, type MorningMail, type MorningRecent, type MorningReply, type MorningState, type MorningTile,
  type MorningWeather,
} from "../morning";
import { Avatar } from "./Avatar";
import { Orb } from "./Orb";

/** Today's hello from GET /api/morning, for the chat on screen. Asked when today's chat opens (and again when the app
 * comes back on screen, so a phone left open overnight gets the new day's); while the hello is being made it asks every
 * 10 s, for up to 3 minutes, then gives up and draws nothing. An old thread never asks. null: nothing to draw. */
export function useMorning(threadId: string | null): MorningReply | null {
  const [reply, setReply] = useState<MorningReply | null>(null);
  const [wake, setWake] = useState(0);
  useEffect(() => {
    const onVisible = () => { if (document.visibilityState === "visible") setWake((n) => n + 1); };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, []);

  const todays = isTodaysChat(threadId, todayISO());
  useEffect(() => {
    if (!todays) return;
    let closed = false;  // the chat changed or closed: answers still on their way are dropped
    let timer: number | undefined;
    let last: MorningState = "none";
    const startedAt = Date.now();
    const ask = async () => {
      try {
        const got = await getJSON<MorningReply>("/api/morning");
        if (closed) return;
        last = got.state;
        setReply(got);
      } catch { /* offline: ask again on the next round if it was being made */ }
      if (closed) return;
      if (keepAsking(last, startedAt, Date.now())) {
        timer = window.setTimeout(() => void ask(), MORNING_ASK_EVERY_MS);
        return;
      }
      if (last === "making") setReply(null);  // three minutes and still not ready: draw nothing
    };
    void ask();
    return () => { closed = true; window.clearTimeout(timer); };
  }, [threadId, todays, wake]);

  if (!todays) return null;
  return reply;
}

/** The hello as the route gave it: "Getting your day ready…" while it's made, the card once it's ready, else nothing. */
export function MorningHello({ reply, onChip }: { reply: MorningReply; onChip: (text: string) => void }) {
  if (reply.state === "making") {
    return (
      <div className="flex items-center gap-3 pt-2 pb-4" role="status">
        <Orb state="thinking" size={28} />
        <span className="text-[14px] font-semibold shimmer-text">Getting your day ready…</span>
      </div>
    );
  }
  if (reply.state === "ready" && reply.card) return <MorningCard card={reply.card} onChip={onChip} />;
  return null;
}

/** Each part of the card rises in after the one above it. */
function Part({ step, className = "", children }: { step: number; className?: string; children: ReactNode }) {
  return <div className={`rise ${className}`} style={{ animationDelay: `${step * 60}ms` }}>{children}</div>;
}

/** Odie's morning hello, B1 ("Odie talks first"): who and when, the greeting, Odie's paragraphs, then the glance
 * (weather, tiles, the nudge, mail, the last few days) and the chips. An empty part isn't drawn. Not a chat message:
 * it is never sent to the model; a chip's tap sends its words as the user's message. */
export function MorningCard({ card, onChip }: { card: Card; onChip: (text: string) => void }) {
  const { name } = usePersona();
  const [before, accent, after] = accentParts(card.greeting, card.accent);
  const time = madeAtTime(card.made_at);
  return (
    <section aria-label="Morning hello" className="flex flex-col gap-2.5 pt-1 pb-6">
      <Part step={0} className="flex items-center gap-2 text-[13.5px] text-muted font-semibold">
        <Avatar size={36} /><span><b className="text-ink-2 font-bold">{name}</b>{time ? ` · ${time}` : ""}</span>
      </Part>
      <Part step={1}>
        <h2 className="text-[26px] leading-[1.18] font-bold tracking-[-0.02em] mt-1 text-balance">
          {before}{accent && <span className="serif text-[30px] tracking-normal">{accent}</span>}{after}
          {card.emoji && <span className="ml-1.5 font-normal">{card.emoji}</span>}
        </h2>
      </Part>
      {card.say.length > 0 && (
        <Part step={2} className="flex flex-col gap-2 mb-1">
          {card.say.map((words) => <p key={words} className="text-[15.5px] leading-[1.55] text-ink-2">{words}</p>)}
        </Part>
      )}
      {card.weather && <Part step={3}><WeatherStrip w={card.weather} /></Part>}
      {card.tiles.length > 0 && <Part step={4}><Tiles tiles={card.tiles} /></Part>}
      {card.nudge && (
        <Part step={5} className="morning-nudge rounded-[22px] px-3.5 py-3 flex items-start gap-3">
          {card.nudge.icon && <span className="text-[20px] leading-[24px] shrink-0" aria-hidden="true">{card.nudge.icon}</span>}
          <span className="text-[14.5px] leading-[1.45] font-medium">{card.nudge.text}</span>
        </Part>
      )}
      {card.mail.length > 0 && (
        <Part step={6}><Rows title="From your mail">{card.mail.map((m) => <MailRow key={m.title + m.note} m={m} />)}</Rows></Part>
      )}
      {card.recent.length > 0 && (
        <Part step={7}><Rows title="Last few days">{card.recent.map((r) => <RecentRow key={r.text} r={r} />)}</Rows></Part>
      )}
      {card.chips.length > 0 && (
        <Part step={8} className="flex flex-wrap gap-2 mt-1">
          {card.chips.map((chip) => (
            <button key={chip} type="button" onClick={() => onChip(chip)} className="pill h-9 px-3.5 text-[13.5px]">{chip}</button>
          ))}
        </Part>
      )}
    </section>
  );
}

function WeatherStrip({ w }: { w: MorningWeather }) {
  return (
    <div className="morning-sky rounded-[22px] px-4 py-3 flex items-center gap-3.5">
      <span className="text-[34px] leading-none font-bold tracking-[-0.03em] tabular-nums">{w.now_c}°</span>
      <div className="min-w-0">
        <b className="block text-[14.5px] leading-tight font-bold truncate">{weatherTitle(w)}</b>
        <span className="block text-[12.5px] text-ink-2 mt-0.5 tabular-nums">High {w.high_c}° · {w.low_c}° tonight</span>
      </div>
    </div>
  );
}

function Tiles({ tiles }: { tiles: MorningTile[] }) {
  const odd = tiles.length % 2 === 1;  // the last tile of an odd count spans both columns, so no hole is left
  return (
    <div className="grid grid-cols-2 gap-2">
      {tiles.map((t, i) => (
        <div key={t.label + t.value} className={`glass rounded-[20px] px-3 py-2.5 min-w-0 ${odd && i === tiles.length - 1 ? "col-span-2" : ""}`}>
          <div className="text-[11px] font-bold uppercase tracking-[.07em] text-muted truncate">{t.label}</div>
          <div className="text-[16px] leading-tight font-bold mt-1 break-words">{t.value}</div>
          {t.note && <div className="text-[12px] leading-[1.35] text-muted mt-0.5 line-clamp-2">{t.note}</div>}
        </div>
      ))}
    </div>
  );
}

function Rows({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="glass rounded-[22px] px-3.5 pt-3 pb-1">
      <h3 className="text-[11px] font-bold uppercase tracking-[.08em] text-muted mb-0.5">{title}</h3>
      <div className="flex flex-col [&>*+*]:border-t [&>*+*]:border-line">{children}</div>
    </div>
  );
}

function MailRow({ m }: { m: MorningMail }) {
  return (
    <div className="flex items-start gap-3 py-2.5">
      <span className="w-8 h-8 shrink-0 rounded-[10px] grid place-items-center bg-ember-tint text-[15px]" aria-hidden="true">{m.icon || "✉️"}</span>
      <div className="flex-1 min-w-0">
        <div className="text-[14px] leading-[1.35] font-semibold break-words">{m.title}</div>
        {m.note && <div className="text-[12.5px] leading-[1.35] text-muted mt-0.5">{m.note}</div>}
      </div>
      {m.pill && <span className="chip chip-warn h-6 self-center shrink-0">{m.pill}</span>}
    </div>
  );
}

const RECENT_MARK: Record<MorningRecent["state"], { mark: string; label: string; tone: string }> = {
  done: { mark: "✓", label: "Done", tone: "bg-good-tint text-good text-[14px]" },
  stuck: { mark: "!", label: "Stuck", tone: "bg-bad-tint text-bad text-[15px]" },
  open: { mark: "…", label: "Open", tone: "bg-well text-muted text-[19px] leading-none pb-[7px]" },  // the dots sit low
};

function RecentRow({ r }: { r: MorningRecent }) {
  const mark = RECENT_MARK[r.state];
  return (
    <div className="flex items-start gap-3 py-2.5">
      <span className={`w-8 h-8 shrink-0 rounded-[10px] grid place-items-center font-extrabold ${mark.tone}`} role="img" aria-label={mark.label}>{mark.mark}</span>
      <div className="flex-1 min-w-0 self-center">
        <div className="text-[14px] leading-[1.35] break-words">{r.text}</div>
        {r.note && <div className="text-[12.5px] leading-[1.35] text-muted mt-0.5">{r.note}</div>}
      </div>
    </div>
  );
}
