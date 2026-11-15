import { useEffect, useState } from "react";
import { getJSON } from "../api";
import { colorFor, elapsed, going, headerWords, type Member, type TeamView } from "../team";
import { Creature, FuzzFilter } from "./Creature";
import { LiveView } from "./LiveView";

const EVERY_MS = 2500;

/** The team at work, under the chat's "Sent it to @chief": the lead and each teammate with its step right now, like
 * Grok's agents side by side. It asks again every 2.5 s while the lead works, then stays as the record; a bot's line
 * opens to its whole report. */
export function TeamCard({ job }: { job: string }) {
  const [view, setView] = useState<TeamView | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [watching, setWatching] = useState<Member | null>(null);

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const load = async () => {
      try {
        const v = await getJSON<TeamView>(`/api/jobs/${job}/team`);
        if (stopped) return;
        setView(v);
        setNow(Date.now());
        if (going(v.lead)) timer = setTimeout(load, EVERY_MS);
      } catch {
        if (!stopped) timer = setTimeout(load, EVERY_MS * 4);  // Odie restarting: try again a little later
      }
    };
    void load();
    return () => { stopped = true; if (timer) clearTimeout(timer); };
  }, [job]);

  if (!view) return null;
  const rows: Member[] = [view.lead, ...view.team];
  const working = going(view.lead);
  return (
    <div className="glass rounded-[22px] p-3.5 flex flex-col gap-2">
      <FuzzFilter />
      <div className="flex items-center gap-2 text-[13px] text-muted">
        {working && <span className="w-2 h-2 rounded-full bg-[var(--t-brand)] animate-pulse shrink-0" />}
        <span className="font-semibold text-ink">{headerWords(view)}</span>
        {!working && <span className="truncate">· {view.title}</span>}
      </div>
      {rows.map((m, i) => (
        <button key={m.job} onClick={() => setOpen(open === m.job ? null : m.job)} aria-expanded={open === m.job}
          className={`text-left flex flex-col gap-1 rounded-[14px] px-2.5 py-2 ${i === 0 ? "" : "ml-3"} active:bg-well`}>
          <div className="flex items-center gap-2">
            {m.look ? <Creature look={m.look} size={24} mood={going(m) ? "working" : ""} /> : (
              <span className="w-6 h-6 rounded-full shrink-0 flex items-center justify-center text-[11px] font-bold text-white"
                style={{ background: colorFor(m.bot) }}>{m.bot.slice(0, 1).toUpperCase()}</span>
            )}
            <span className="text-[14px] font-semibold">{m.bot}</span>
            {m.model && m.own_model && <span className="text-[11.5px] text-muted truncate">{m.model}</span>}
            {going(m) && m.tab && (
              <span role="button" tabIndex={0} onClick={(e) => { e.stopPropagation(); setWatching(m); }}
                onKeyDown={(e) => { if (e.key === "Enter") { e.stopPropagation(); setWatching(m); } }}
                className="ml-1 px-2.5 h-7 rounded-full bg-ember text-on-ember text-[12px] font-semibold inline-flex items-center">Watch</span>
            )}
            <span className="ml-auto text-[11.5px] text-muted tabular-nums shrink-0">
              {going(m) ? "" : m.status === "done" && m.outcome !== "blocked" ? "✓ " : m.status === "done" ? "⛔ " : "✕ "}
              {elapsed(m, now)}{m.calls ? ` · ${m.calls} steps` : ""}
            </span>
          </div>
          <div className={`text-[13px] leading-[18px] ${going(m) ? "text-ink-2" : "text-muted"} ${open === m.job ? "" : "line-clamp-2"}`}>
            {going(m) ? `${m.now}…` : m.now}
          </div>
          {open === m.job && !going(m) && m.report && (
            <div className="text-[13px] leading-[18px] whitespace-pre-wrap text-ink-2 border-t border-line pt-1.5">{m.report}</div>
          )}
        </button>
      ))}
      {watching?.tab && (
        <LiveView tab={watching.tab} site={hostOf(watching.url)} chat={false} watch who={watching.bot}
          doing={[view.lead, ...view.team].find((x) => x.job === watching.job)?.now} onClose={() => setWatching(null)} />
      )}
    </div>
  );
}

/** A page's site for the bar: "https://www.amazon.in/x" -> "amazon.in"; nothing -> "". */
function hostOf(url: string | null | undefined): string {
  try { return new URL(url ?? "").host.replace(/^www\./, ""); } catch { return ""; }
}

/** What a finished answer took, as one pill above it (Fable's design): "3 bots · 5:02 · 83 steps", or for one bot
 * "0:14 · 6 steps". Tapping it opens the team card as it ended: who did what, each report. Nothing to say -> nothing. */
export function TurnPill({ job }: { job: string }) {
  const [view, setView] = useState<TeamView | null>(null);
  const [open, setOpen] = useState(false);
  useEffect(() => { getJSON<TeamView>(`/api/jobs/${job}/team`).then(setView).catch(() => setView(null)); }, [job]);
  if (!view || going(view.lead)) return null;
  const steps = [view.lead, ...view.team].reduce((n, m) => n + m.calls, 0);
  if (!steps && !(view.made ?? []).length) return null;
  const time = elapsed(view.lead, Date.now());
  const words = `${view.team.length ? `${view.team.length} bot${view.team.length === 1 ? "" : "s"} · ` : ""}${time ? `${time} · ` : ""}${steps} steps`;
  return (
    <div className="flex flex-col gap-2">
      <button onClick={() => setOpen((o) => !o)} aria-expanded={open}
        className="self-start h-7 px-2.5 rounded-full bg-well text-[12px] text-muted font-semibold inline-flex items-center gap-1.5">
        {view.team.length > 0 && <span className="inline-flex -space-x-1.5">{view.team.slice(0, 4).map((m) => m.look ? <Creature key={m.job} look={m.look} size={16} /> : null)}</span>}
        {words} <span aria-hidden="true">{open ? "▴" : "▾"}</span>
      </button>
      {open && <TeamCard job={job} />}
      {(view.made ?? []).length > 0 && (
        <div className="flex flex-wrap gap-2">
          {view.made!.map((name) => <a key={name} href={`#bot/${name}/new`} className="chip chip-soft">Meet {name} ›</a>)}
        </div>
      )}
    </div>
  );
}
