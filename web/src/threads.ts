import { userLocale } from "./locale";
export type Thread = { id: string; title: string; renamed: boolean; date: string; messages: number; started: number; updated: number; pinned: boolean; snippet: string | null };

/** Pinned first, then by day: Today, Yesterday, This week, then by month. */
export function groupThreads(list: Thread[], today: string): { label: string; items: Thread[] }[] {
  const out: { label: string; items: Thread[] }[] = [];
  const add = (label: string, t: Thread) => { const g = out.find((x) => x.label === label); if (g) g.items.push(t); else out.push({ label, items: [t] }); };
  const day = (iso: string) => Date.parse(iso + "T00:00:00");
  for (const t of list) {
    if (t.pinned) { add("Pinned", t); continue; }
    const ago = Math.round((day(today) - day(t.date)) / 86400000);
    add(ago <= 0 ? "Today" : ago === 1 ? "Yesterday" : ago < 7 ? "This week"
      : new Date(t.date + "T00:00:00").toLocaleDateString(userLocale(), { month: "long", year: "numeric" }), t);
  }
  return out;
}

/** "18:40" for today, "Sat 3 Oct" otherwise. */
export function whenText(t: Thread, today: string): string {
  const d = new Date(t.updated * 1000);
  return t.date === today ? d.toLocaleTimeString(userLocale(), { hour: "2-digit", minute: "2-digit", hour12: false })
    : new Date(t.date + "T00:00:00").toLocaleDateString(userLocale(), { weekday: "short", day: "numeric", month: "short" });
}

/** Does a live message belong in the chat being shown? Today's view shows today's segments; a thread shows only itself.
 *  `owner` is the personality the message's thread belongs to and `pick` the one on screen ("" = everyday Odie): a
 *  message of another's never belongs. A personality's chat with no thread shown yet takes its own first message. */
export function belongsHere(sessionId: string | undefined, threadId: string | null, today: string, owner = "", pick = ""): boolean {
  if (owner !== pick) return false;
  if (!sessionId) return threadId === null;
  if (threadId) return sessionId === threadId;
  if (pick) return true;
  return sessionId.startsWith(`chat-${today}`);
}
