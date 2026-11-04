export type JobRow = { id: string; kind: string; title: string; status: string; runs: number; outcome: string | null; error: string | null;
  every_minutes: number; next_run_at: string | null; report: string; started_at: string | null; ended_at: string | null };

/** One line under a job's title: its state in words.
 *    running, run 1          -> "working"
 *    waiting, every 60, next 10:00 -> "every 60 min · next 10:00"
 *    done, ready             -> "done"
 *    done, blocked           -> "stuck"
 *    failed, "no progress…"  -> "didn't finish · no progress…" */
export function jobLine(j: JobRow): string {
  if (j.status === "running" || j.status === "queued") return j.every_minutes ? `checking (run ${j.runs})` : "working";
  if (j.status === "waiting") return `every ${j.every_minutes} min · next ${(j.next_run_at ?? "").slice(11, 16)}`;
  if (j.status === "stopped") return "stopped";
  if (j.status === "failed") return `didn't finish${j.error ? ` · ${j.error}` : ""}`;
  if (j.outcome === "blocked") return "stuck";
  return j.every_minutes ? `finished after ${j.runs} reports` : "done";
}
