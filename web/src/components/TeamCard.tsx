import { useEffect, useState } from "react";
import { getJSON } from "../api";
import { colorFor, elapsed, going, headerWords, type Member, type TeamView } from "../team";

const EVERY_MS = 2500;

/** The team at work, under the chat's "Sent it to @chief": the lead and each teammate with its step right now, like
 * Grok's agents side by side. It asks again every 2.5 s while the lead works, then stays as the record; a bot's line
 * opens to its whole report. */
export function TeamCard({ job }: { job: string }) {
  const [view, setView] = useState<TeamView | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());

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
      <div className="flex items-center gap-2 text-[13px] text-muted">
        {working && <span className="w-2 h-2 rounded-full bg-iris animate-pulse" />}
        <span className="font-semibold text-ink">{view.title}</span>
        <span>· {headerWords(view)}</span>
      </div>
      {rows.map((m, i) => (
        <button key={m.job} onClick={() => setOpen(open === m.job ? null : m.job)} aria-expanded={open === m.job}
          className={`text-left flex flex-col gap-1 rounded-[14px] px-2.5 py-2 ${i === 0 ? "" : "ml-3"} active:bg-well`}>
          <div className="flex items-center gap-2">
            <span className="w-6 h-6 rounded-full shrink-0 flex items-center justify-center text-[11px] font-bold text-white"
              style={{ background: colorFor(m.bot) }}>{m.bot.slice(0, 1).toUpperCase()}</span>
            <span className="text-[14px] font-semibold">{m.bot}</span>
            {m.model && <span className="text-[11.5px] text-muted truncate">{m.model}</span>}
            <span className="ml-auto text-[11.5px] text-muted tabular-nums shrink-0">
              {going(m) ? "" : m.status === "done" && m.outcome !== "blocked" ? "✓ " : m.status === "done" ? "⛔ " : "✕ "}
              {elapsed(m, now)}{m.calls ? ` · ${m.calls} steps` : ""}
            </span>
          </div>
          <div className={`text-[13px] leading-[18px] ${going(m) ? "text-ink-2" : "text-muted"} ${open === m.job ? "" : "truncate"}`}>
            {going(m) ? `${m.now}…` : m.now}
          </div>
          {open === m.job && !going(m) && m.report && (
            <div className="text-[13px] leading-[18px] whitespace-pre-wrap text-ink-2 border-t border-line pt-1.5">{m.report}</div>
          )}
        </button>
      ))}
    </div>
  );
}
