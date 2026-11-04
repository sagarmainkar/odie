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

/** Whether the chat on screen is today's: the main view (no thread), or a segment of today's chat opened from Threads.
 * (null, "2026-11-04") -> true; ("chat-2026-11-04-2", "2026-11-04") -> true; ("chat-2026-10-30-5", "2026-11-04") -> false. */
export function isTodaysChat(threadId: string | null, today: string): boolean {
  if (threadId === null) return true;
  return threadId.startsWith(`chat-${today}`);
}

/** Whether the morning hello is drawn above the chat: in today's chat, while the hello is ready or being made.
 * Today's chat, "ready" -> true (the card); today's chat, "making" -> true (the "Getting your day ready…" line);
 * "none" -> false (nothing); an old thread like "chat-2026-10-30-5" -> false, whatever the state. */
export function shouldShowMorning(threadId: string | null, today: string, state: MorningState | string): boolean {
  if (!isTodaysChat(threadId, today)) return false;
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
