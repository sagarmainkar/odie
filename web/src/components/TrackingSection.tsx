import { useCallback, useEffect, useState } from "react";
import { getJSON } from "../api";
import { Blocks } from "../blocks/Blocks";
import { parseBlocks } from "../blocks/parse";
import { useLive } from "../live";
import { ago, everyText, ordered, pageText, setSignin, type Tracker } from "../trackers";
import { Icon } from "./Tile";

/** Today: what Odie is keeping an eye on. One card per tracker, newest result first; hidden when there are none. */
export function TrackingSection() {
  const [rows, setRows] = useState<Tracker[]>([]);
  const [busy, setBusy] = useState<number | null>(null);
  const [problem, setProblem] = useState<{ id: number; why: string } | null>(null);
  const load = useCallback(() => { getJSON<{ trackers: Tracker[] }>("/api/trackers").then((d) => setRows(ordered(d.trackers))).catch(() => {}); }, []);
  useEffect(() => { load(); const t = setInterval(load, 60_000); return () => clearInterval(t); }, [load]);
  useLive(useCallback((e: { type: string }) => { if (e.type === "message") load(); }, [load]), load);

  async function act(id: number, action: string) {
    setBusy(id);
    try { await fetch(`/api/trackers/${id}/${action}`, { method: "POST" }); } finally {
      setBusy(null);
      load();
      if (action === "check") setTimeout(load, 20_000);  // the check runs in the background
    }
  }
  async function signin(id: number, allow: boolean) {
    setBusy(id);
    const why = await setSignin(id, allow);
    setProblem(why ? { id, why } : null);
    setBusy(null);
    load();
  }
  if (!rows.length) return null;
  return (
    <section className="flex flex-col gap-2">
      <div className="text-[13px] leading-5 font-bold text-muted px-1.5 flex items-center gap-1.5"><Icon name="bell" size={14} /> Tracking</div>
      {rows.map((t) => {
        const blocks = t.blocks ? parseBlocks(JSON.stringify(t.blocks)) : null;
        const live = t.status === "active";
        return (
          <div key={t.id} className={`glass rounded-[24px] px-4 py-3.5 flex flex-col gap-1.5 ${live ? "" : "opacity-70"}`}>
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full shrink-0 ${live ? "bg-good" : "bg-dim"}`} />
              <b className="text-[15px] font-semibold flex-1 min-w-0 truncate">{t.title}</b>
              {t.status !== "active" && <span className="chip chip-soft">{t.status === "paused" ? "Paused" : t.status === "done" ? "Done" : t.status}</span>}
            </div>
            <div className="text-[14px] leading-[20px] text-ink-2">{t.last_summary ?? "First check coming up…"}</div>
            {t.page_url && (t.status === "active" || t.status === "paused") && (
              <div className="flex items-center gap-2 text-[12.5px] text-muted">
                <span className="flex-1 min-w-0 truncate">{t.signin_allowed ? "Signed in" : "Not signed in"} · {pageText(t.page_url)}</span>
                <button role="switch" aria-checked={!!t.signin_allowed} aria-label="Check signed in" disabled={busy === t.id}
                  onClick={() => void signin(t.id, !t.signin_allowed)} className="pill pill-flat h-8 px-3 text-[12.5px]">{t.signin_allowed ? "On" : "Off"}</button>
              </div>
            )}
            {problem?.id === t.id && <div className="text-[12.5px] text-warn">{problem.why}</div>}
            {blocks && blocks.length > 0 && <Blocks blocks={blocks} />}
            <div className="flex items-center gap-2 text-[12px] text-dim">
              <span className="flex-1 min-w-0 truncate">{ago(t.last_checked_at)} · {everyText(t.schedule)}</span>
              {(t.status === "active" || t.status === "paused") && (
                <>
                  {live && <button aria-label="Check now" disabled={busy === t.id} onClick={() => act(t.id, "check")} className="pill pill-flat w-8 h-8 px-0"><Icon name="refresh" size={14} /></button>}
                  <button aria-label={live ? "Pause" : "Resume"} disabled={busy === t.id} onClick={() => act(t.id, live ? "pause" : "resume")} className="pill pill-flat h-8 px-3 text-[12.5px]">{live ? "Pause" : "Resume"}</button>
                  <button aria-label="Stop" disabled={busy === t.id} onClick={() => { if (confirm(`Stop tracking ${t.title}?`)) void act(t.id, "stop"); }} className="pill pill-flat w-8 h-8 px-0"><Icon name="x" size={14} /></button>
                </>
              )}
            </div>
          </div>
        );
      })}
    </section>
  );
}
