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

const IMPORTED_FROM = 101;  // imported threads are chat-<date>-101 and up (odie/replay_threads.py FIRST_SEGMENT)

/** Is this thread part of everyday Odie's chat of `today`? "chat-2026-10-05" and "chat-2026-10-05-2" -> yes;
 *  an imported "chat-2026-10-05-101" -> no; "chat-2026-10-04" -> no. */
function isTodaysPart(id: string, today: string): boolean {
  if (id === `chat-${today}`) return true;
  if (!id.startsWith(`chat-${today}-`)) return false;
  const number = Number(id.slice(`chat-${today}-`.length));
  return number < IMPORTED_FROM;
}

/** The listed thread that is exactly the chat the drawer's top row ("Today's chat" / "Current chat") opens, so the
 *  list doesn't show it a second time; null when none is. A pinned one stays listed: its star is how it is unpinned.
 *    everyday Odie, today's only chat "chat-2026-10-05"            -> "chat-2026-10-05"
 *    everyday Odie, "chat-2026-10-05" and a New chat "-2" today      -> null (the top row shows both together)
 *    a personality whose current thread is "chat-2026-10-03-4"       -> "chat-2026-10-03-4"
 *    a personality whose history hasn't answered yet (no thread)     -> null */
export function sameAsTopRow(list: Thread[], today: string, pick: string, pickThread: string | null): string | null {
  let topRow: Thread | undefined;
  if (pick) {
    topRow = list.find((t) => t.id === pickThread);
  } else {
    const todaysParts = list.filter((t) => isTodaysPart(t.id, today));
    if (todaysParts.length === 1) topRow = todaysParts[0];
  }
  if (!topRow || topRow.pinned) return null;
  return topRow.id;
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
