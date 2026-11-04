// The morning hello: GET /api/morning, the card Odie draws above today's chat. The shape mirrors the route's contract,
// which Odie for Mac reads too, so a change here is a change there.
import { userLocale } from "./locale";

export type MorningState = "ready" | "making" | "none";
export type MorningWeather = { place: string; now_c: number; high_c: number; low_c: number; words: string };
export type MorningTile = { label: string; value: string; note: string };
export type MorningNudge = { icon: string; text: string };
export type MorningMail = { icon: string; title: string; note: string; pill: string };
export type MorningRecent = { state: "done" | "stuck" | "open"; text: string; note: string };

export type MorningCard = {
  greeting: string;
  accent: string;  // a word inside the greeting, set in serif italic, or ""
  emoji: string;  // at most 2 characters, or ""
  say: string[];  // 0-2 paragraphs (none on a fallback card)
  weather: MorningWeather | null;
  tiles: MorningTile[];  // 0-4
  nudge: MorningNudge | null;
  mail: MorningMail[];  // 0-6
  recent: MorningRecent[];  // 0-5
  chips: string[];  // 0-4; a tap sends the words as the user's message
  day: string;
  made_at: string;
  fallback: boolean;  // a plain card built by code: no say, no recent, no chips
};

export type MorningReply = { state: MorningState; day: string; card: MorningCard | null };

export const MORNING_ASK_EVERY_MS = 10_000;  // while the hello is made, the card asks again this often
export const MORNING_ASK_FOR_MS = 3 * 60_000;  // and gives up after this long

/** The greeting split around its accent word, so the word can be set in serif italic.
 * ("Morning, Asha. Four days to Diwali", "Diwali") -> ["Morning, Asha. Four days to ", "Diwali", ""];
 * ("Good morning, Asha.", "Diwali") -> ["Good morning, Asha.", "", ""]. */
export function accentParts(greeting: string, accent: string): [string, string, string] {
  const at = accent ? greeting.indexOf(accent) : -1;
  if (at < 0) return [greeting, "", ""];
  return [greeting.slice(0, at), accent, greeting.slice(at + accent.length)];
}

/** Whether the hello is today's: the route says which morning it belongs to, and from midnight to 05:00 that is still
 * yesterday's, which the card doesn't draw as today's.
 * day "2026-11-04" on 4 Nov -> true; day "2026-11-04" at 01:30 on 5 Nov -> false. */
export function isTodaysHello(reply: MorningReply, today: string): boolean {
  return reply.day === today;
}

/** Whether the chat on screen can start at the top of the day: the main view (no thread), or the day's first segment
 * opened from Threads. Only these ask for the hello.
 * (null, "2026-11-04") -> true; ("chat-2026-11-04", "2026-11-04") -> true; ("chat-2026-11-04-2", "2026-11-04") -> false
 * (a later segment); ("chat-2026-10-30-5", "2026-11-04") -> false (an old thread). */
export function isDayStartChat(threadId: string | null, today: string): boolean {
  if (threadId === null) return true;
  return threadId === `chat-${today}`;
}

/** What the chat on screen knows about its history, for the morning card. */
export type ChatOnScreen = {
  threadId: string | null;
  historyLoaded: boolean;  // this chat's history has answered (before it does, nothing says where the day starts)
  earlier: number;  // how many older messages are still to load above (0: the loaded history reaches the day's start)
  cut: boolean;  // a "/new" hid the messages above it: what's shown is a later conversation, not the day's first
};

/** What the chat on screen knows about its history, for the morning card: whether its own history has answered, and
 * whether a "/new" cut it. `loaded` is the last history that answered (which chat it was for, and its cut).
 * Today's view, its history answered with no cut, earlier 0 -> loaded, no cut (the card may show);
 * the same after "/new" -> loaded, cut; nothing answered yet, or the last answer was another thread's -> not loaded. */
export function chatOnScreen(threadId: string | null, loaded: { threadId: string | null; cut: boolean } | null, earlier: number): ChatOnScreen {
  if (loaded === null || loaded.threadId !== threadId) return { threadId, historyLoaded: false, earlier, cut: false };
  return { threadId, historyLoaded: true, earlier, cut: loaded.cut };
}

/** Whether the morning card is drawn: only at the true top of the day, while the hello is ready or being made. That is
 * the main view or the day's first segment, its history loaded, reaching the day's start (nothing earlier to load), with
 * no "/new" above it. A chat after "/new", or a later segment, gets the plain empty-chat greeting instead.
 * The main view at 07:40, loaded, earlier 0, no cut, "ready" -> true (the card);
 * the same, "making" -> true (the "Getting your day ready…" line); the same, "none" -> false;
 * after "/new" at 21:00 (cut) -> false; 30 more messages to load above (earlier 30) -> false;
 * history not answered yet -> false (no flash of the card); "chat-2026-11-04-2" -> false; an old thread -> false. */
export function shouldShowMorning(chat: ChatOnScreen, today: string, state: MorningState | string): boolean {
  if (!isDayStartChat(chat.threadId, today)) return false;
  if (!chat.historyLoaded) return false;
  if (chat.earlier > 0) return false;
  if (chat.cut) return false;
  return state === "ready" || state === "making";
}

/** Whether to ask for the hello again: only while it's being made, and for three minutes at most.
 * "making" 30 s after the first ask -> true; "making" after 3 minutes -> false (give up); "ready" or "none" -> false. */
export function keepAsking(state: MorningState, startedAt: number, now: number): boolean {
  if (state !== "making") return false;
  return now - startedAt < MORNING_ASK_FOR_MS;
}

/** The weather strip's bold line: the sky and the place, or whichever is known.
 * Clear, Pune -> "Clear in Pune"; Clear, no place -> "Clear"; no words, Pune -> "Today in Pune"; neither -> "Today". */
export function weatherTitle(w: MorningWeather): string {
  const sky = w.words || "Today";
  if (!w.place) return sky;
  return `${sky} in ${w.place}`;
}

/** When the hello was made, as the chat shows its times: "2026-11-04T07:31:12+05:30" -> "7:31 am" (en-IN). */
export function madeAtTime(madeAt: string): string {
  const when = new Date(madeAt);
  if (Number.isNaN(when.getTime())) return "";
  return when.toLocaleTimeString(userLocale(), { hour: "numeric", minute: "2-digit" });
}
