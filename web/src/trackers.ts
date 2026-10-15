export type Tracker = {
  id: number; title: string; check_text: string; status: "active" | "paused" | "done" | "stopped" | "failed";
  schedule: { minutes?: number; times?: string[]; days?: number[] | null }; notify: string; condition: string;
  last_summary: string | null; last_checked_at: string | null; next_check_at: string; until_at: string; blocks: unknown[] | null; fails: number;
  page_url: string | null; signin_allowed: number;  // a signed-in tracker's page, and the user's Allow
};

/** "every 15 min", "every 2 h", "daily 09:00", "Mon 09:00" */
export function everyText(s: Tracker["schedule"]): string {
  if (s.minutes) return s.minutes % 1440 === 0 ? `every ${s.minutes / 1440 === 1 ? "day" : `${s.minutes / 1440} days`}`
    : s.minutes % 60 === 0 ? `every ${s.minutes / 60} h` : `every ${s.minutes} min`;
  const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const d = s.days?.length ? (s.days.join() === "0,1,2,3,4" ? "weekdays" : s.days.map((i) => days[i]).join(", ")) : "daily";
  return `${d} ${(s.times ?? []).join(", ")}`;
}

/** "just now", "12 min ago", "3 h ago", "2 d ago" */
export function ago(iso: string | null, now = Date.now()): string {
  if (!iso) return "not checked yet";
  const m = Math.max(0, Math.round((now - Date.parse(iso)) / 60000));
  return m < 1 ? "just now" : m < 60 ? `${m} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} d ago`;
}

/** Active first, then paused; finished ones only if they ended recently (the server already limits that). */
export function ordered(ts: Tracker[]): Tracker[] {
  const rank = { active: 0, paused: 1, done: 2, failed: 2, stopped: 3 } as const;
  return [...ts].filter((t) => t.status !== "stopped").sort((a, b) => rank[a.status] - rank[b.status] || b.id - a.id);
}

/** "amazon.in/gp/your-account/order-history": a signed-in tracker's page, short. */
export function pageText(url: string): string {
  try {
    const u = new URL(url);
    return (u.hostname.replace(/^www\./, "") + u.pathname).replace(/\/$/, "");
  } catch {
    return url;
  }
}

/** The user's tap: may this tracker check its page signed in? null when done, else why not. */
export async function setSignin(id: number, allow: boolean): Promise<string | null> {
  const r = await fetch(`/api/trackers/${id}/signin`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ allow }) });
  if (r.ok) return null;
  try { return (await r.json()).detail ?? "That didn't work."; } catch { return "That didn't work."; }
}
