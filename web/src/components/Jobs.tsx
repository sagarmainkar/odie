import { useCallback, useEffect, useState } from "react";
import { getJSON, postJSON } from "../api";
import { useLive } from "../live";
import { jobLine, type JobRow } from "../jobs";
import type { JobAsk } from "../bots";
import { LiveView } from "./LiveView";

type Action = { ts: string; tool: string; args: string; result_chars: number | null; refused: string | null; error: string | null };
type Teammate = { id: string; bot: string; title: string; status: string; outcome: string | null; report: string };
type Detail = JobRow & { actions: Action[]; brief: string; teammates?: Teammate[] };
type Listing = { running: JobRow[]; recent: JobRow[]; asks?: JobAsk[] };

function hm(ts: string) { return ts.slice(11, 19); }

export function Jobs() {
  const [data, setData] = useState<Listing | null>(null);
  const [open, setOpen] = useState<Record<string, Detail | "loading">>({});
  const [signing, setSigning] = useState<JobAsk | null>(null);
  const load = useCallback(() => { getJSON<Listing>("/api/jobs").then(setData).catch(() => setData(null)); }, []);
  useEffect(load, [load]);
  useLive(useCallback((e: { type: string }) => { if (e.type === "message") load(); }, [load]), load);
  if (!data || (data.running.length === 0 && data.recent.length === 0 && !(data.asks ?? []).length)) return null;

  async function more(id: string) {
    if (open[id]) { setOpen((o) => { const { [id]: _gone, ...rest } = o; return rest; }); return; }
    setOpen((o) => ({ ...o, [id]: "loading" }));
    try { const d = await getJSON<Detail>(`/api/jobs/${id}`); setOpen((o) => ({ ...o, [id]: d })); } catch { setOpen((o) => { const { [id]: _gone, ...rest } = o; return rest; }); }
  }
  async function stop(id: string) { try { await postJSON(`/api/jobs/${id}/stop`, {}); } finally { load(); } }
  async function retry(id: string) { try { await postJSON(`/api/jobs/${id}/retry`, {}); } finally { load(); } }
  /** Only these buttons answer a bot's question: no chat message or tool can (odie/workers/asks.py). */
  async function answer(id: string, said: "yes" | "no") { try { await postJSON(`/api/jobs/asks/${id}`, { answer: said }); } finally { load(); } }
  const asks = data.asks ?? [];

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
      {asks.length > 0 && (
        <div className="glass rounded-[26px] overflow-hidden">
          {asks.map((a) => (
            <div key={a.id} className="border-b border-line last:border-b-0 px-4 py-3 flex flex-col gap-2">
              <div className="text-[15px] leading-5">{a.kind === "sign_in" ? "🔑 " : "✋ "}{a.text}</div>
              <div className="text-[12.5px] leading-4 text-muted">{a.why ? `${a.why} · ` : ""}{titleOf(data, a.job_id)}</div>
              <div className="flex gap-2">
                {a.kind === "tap" ? (
                  <>
                    <button onClick={() => void answer(a.id, "yes")} className="h-10 px-4 rounded-[14px] bg-ember text-on-ember font-semibold text-[14px]">Allow</button>
                    <button onClick={() => void answer(a.id, "no")} className="pill h-10 px-4 text-[14px]">Deny</button>
                  </>
                ) : (
                  <>
                    {a.card?.tab && <button onClick={() => setSigning(a)} className="h-10 px-4 rounded-[14px] bg-ember text-on-ember font-semibold text-[14px]">Sign in</button>}
                    <button onClick={() => void answer(a.id, "yes")} className="pill h-10 px-4 text-[14px]">Done</button>
                    <button onClick={() => void answer(a.id, "no")} className="pill h-10 px-4 text-[14px]">Skip</button>
                  </>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
      {signing?.card?.tab && (
        <LiveView tab={signing.card.tab} site={signing.site ?? ""} chat={false}
          onClose={(r) => { const a = signing; setSigning(null); if (r?.done) void answer(a.id, "yes"); }} />
      )}
      <div className="glass rounded-[26px] overflow-hidden">
        {data.running.filter(isLead).map((j) => row(j, true))}
        {data.recent.filter(isLead).map((j) => row(j, false))}
      </div>
    </section>
  );
}

/** The job a question comes from, by its title: a teammate's job shows as "researcher: find tides" (its row is in the
 * listing); one not listed falls back to its id. */
function titleOf(data: Listing, jobId: string): string {
  const all = [...data.running, ...data.recent];
  return all.find((j) => j.id === jobId)?.title ?? jobId;
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
