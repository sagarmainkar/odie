/** The live team card (odie/workers/progress.py): each bot's step right now, Grok-style. */

export type Member = { job: string; bot: string; look?: { shape: string; color: string; eyes: string } | null; own_model?: boolean; status: string; outcome: string | null; now: string; model: string;
  report: string; calls: number; started_at: string | null; ended_at: string | null;
  tab?: string | null; url?: string | null };  // its browser tab, when it has used the browser: Watch opens it live
export type TeamView = { title: string; lead: Member; team: Member[]; made?: string[] };  // made: bots this turn made

const COLORS = ["#5b8def", "#2fb67c", "#f08a3c", "#d65db1", "#8b6cf6", "#e0b43a", "#3cb4c8"];

/** A bot's colour, the same every time for the same name: "chief" is always violet; others by their letters. */
export function colorFor(bot: string): string {
  if (bot === "chief") return "#8b6cf6";
  let h = 0;
  for (const ch of bot) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return COLORS[h % COLORS.length];
}

/** Still at work? queued, running, or a scheduled bot between runs -> true; done, failed, stopped -> false. */
export function going(m: Member): boolean {
  return m.status === "queued" || m.status === "running" || m.status === "waiting";
}

/** How long a bot has worked, or worked in all: 75 s -> "1:15"; 9 s -> "0:09"; not started -> "". */
export function elapsed(m: Member, nowMs: number): string {
  if (!m.started_at) return "";
  const start = Date.parse(m.started_at);
  const end = m.ended_at ? Date.parse(m.ended_at) : nowMs;
  const s = Math.max(0, Math.round((end - start) / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** The card's header: "Team at work · 2 of 3 done" (one bot: "Working") while it works; "done" / "didn't finish" /
 * "stopped" after. */
export function headerWords(v: TeamView): string {
  if (going(v.lead)) {
    if (!v.team.length) return "Working";
    const done = v.team.filter((m) => !going(m)).length;
    return `Team at work · ${done} of ${v.team.length} done`;
  }
  if (v.lead.status === "failed") return "didn't finish";
  if (v.lead.status === "stopped") return "stopped";
  return "done";
}
