import { useCallback, useEffect, useState } from "react";
import { getJSON, postJSON } from "../api";
import { useLive } from "../live";
import { jobLine, type JobRow } from "../jobs";

type Action = { ts: string; tool: string; args: string; result_chars: number | null; refused: string | null; error: string | null };
type Teammate = { id: string; bot: string; title: string; status: string; outcome: string | null; report: string };
type Detail = JobRow & { actions: Action[]; brief: string; teammates?: Teammate[] };
type Listing = { running: JobRow[]; recent: JobRow[] };  // questions bots wait on show on the Bots card

function hm(ts: string) { return ts.slice(11, 19); }

export function Jobs() {
  const [data, setData] = useState<Listing | null>(null);
  const [open, setOpen] = useState<Record<string, Detail | "loading">>({});
  const load = useCallback(() => { getJSON<Listing>("/api/jobs").then(setData).catch(() => setData(null)); }, []);
  useEffect(load, [load]);
  useLive(useCallback((e: { type: string }) => { if (e.type === "message") load(); }, [load]), load);
  if (!data || (data.running.length === 0 && data.recent.length === 0)) return null;

  async function more(id: string) {
    if (open[id]) { setOpen((o) => { const { [id]: _gone, ...rest } = o; return rest; }); return; }
    setOpen((o) => ({ ...o, [id]: "loading" }));
    try { const d = await getJSON<Detail>(`/api/jobs/${id}`); setOpen((o) => ({ ...o, [id]: d })); } catch { setOpen((o) => { const { [id]: _gone, ...rest } = o; return rest; }); }
  }
  async function stop(id: string) { try { await postJSON(`/api/jobs/${id}/stop`, {}); } finally { load(); } }
  async function retry(id: string) { try { await postJSON(`/api/jobs/${id}/retry`, {}); } finally { load(); } }

  const row = (j: JobRow, going: boolean) => {
    const d = open[j.id];
    return (
      <div key={j.id} className="border-b border-line last:border-b-0">
        <div className="flex items-center gap-3 px-4 min-h-[56px]">
          <span className={`w-2 h-2 rounded-full shrink-0 ${going ? "bg-iris" : j.status === "failed" || j.outcome === "blocked" ? "bg-ember" : "bg-line-2"}`} />
          <div className="flex-1 min-w-0">
            <div className="text-[15px] leading-5 truncate">{j.title}</div>
            <div className="text-[12.5px] leading-4 text-muted truncate">{jobLine(j)}{teamWords(data, j.id)} · {j.id}</div>
          </div>
          {going && <button onClick={() => void stop(j.id)} className="pill h-9 px-3 text-[13px]">Stop</button>}
          {!going && (j.status === "failed" || j.status === "stopped") && <button onClick={() => void retry(j.id)} className="pill h-9 px-3 text-[13px]">Retry</button>}
          <button onClick={() => void more(j.id)} className="pill h-9 px-3 text-[13px]">{d ? "Less" : "More"}</button>
        </div>
        {d && d !== "loading" && (
          <div className="px-4 pb-3 flex flex-col gap-2 text-[13px] leading-[18px]">
            {d.report && <div className="whitespace-pre-wrap text-ink-2">{d.report}</div>}
            {(d.teammates ?? []).length > 0 && (
              <div className="flex flex-col gap-2">
                <div className="text-muted">The team</div>
                {d.teammates!.map((t) => (
                  <details key={t.id} className="rounded-[14px] bg-well px-3 py-2">
                    <summary className="cursor-pointer"><span className="font-semibold">{t.bot}</span> · {t.status === "done" ? (t.outcome === "blocked" ? "stuck" : "done") : t.status}</summary>
                    <div className="mt-1 text-[12.5px] text-muted">{t.title}</div>
                    {t.report && <div className="mt-1 whitespace-pre-wrap text-ink-2">{t.report}</div>}
                  </details>
                ))}
              </div>
            )}
            <div className="text-muted">{d.actions.length} call{d.actions.length === 1 ? "" : "s"}</div>
            <div className="flex flex-col gap-1 font-mono text-[12px] leading-4 text-muted">
              {d.actions.map((a, i) => (
                <div key={i} className="truncate">
                  {hm(a.ts)} {a.tool}{a.refused ? ` · refused: ${a.refused}` : a.error ? ` · error: ${a.error}` : ""} {a.args}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    );
  };

  return (
    <section className="flex flex-col gap-2">
      <div className="px-1 text-[13px] font-semibold text-muted">Jobs</div>
      <div className="glass rounded-[26px] overflow-hidden">
        {data.running.filter(isLead).map((j) => row(j, true))}
        {data.recent.filter(isLead).map((j) => row(j, false))}
      </div>
    </section>
  );
}


/** A job shown on its own row: everything but a teammate's part, which its chief's row counts instead. */
function isLead(j: JobRow): boolean { return !j.parent_id; }

/** A chief's teammates after its state: none -> ""; three, all ended -> " · 3 teammates"; three with one still at
 * work -> " · 2 of 3 teammates done". */
function teamWords(data: Listing, jobId: string): string {
  const team = [...data.running, ...data.recent].filter((j) => j.parent_id === jobId);
  if (!team.length) return "";
  const going = team.filter((j) => j.status === "running" || j.status === "queued").length;
  if (going) return ` · ${team.length - going} of ${team.length} teammates done`;
  return ` · ${team.length} teammate${team.length === 1 ? "" : "s"}`;
}
