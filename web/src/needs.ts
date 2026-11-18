import type { IconName, TileColor } from "./components/Tile";
import type { Media } from "./media";

/** What a card's button does, decided by the server (odie/watch/needs.py, odie/loops/cards.py). "later": put the card
 *  off until 09:00 tomorrow (POST /api/needs_you/later with its ref); "open": open the page the server built (a pull
 *  request); "loop_done": a loop's Done (POST /api/loops/<id>/done). */
export type NeedAction = { label: string; action: "chat" | "dismiss" | "done_task" | "snooze_task" | "later" | "open" | "loop_done"
  | "job_retry" | "job_allow" | "job_clear" | "merge" | "recipe_use" | "recipe_no" | "show_output"; value: string | number };

/** One card in a Pulse's "Needs you": a watch item from mail, or one of the user's own reminders. Every card has the
 *  same three buttons: its one move (main), Done (other) and Later (later; an older server sends no Later). */
export type Need = { ref: string; title: string; why: string; brief?: string; icon: IconName; badge: string; ask: string; main: NeedAction; other: NeedAction; later?: NeedAction;
  evidence?: { at: string; source: string; fact: string }[]; output?: string;  // a tested PR's card: Why? and the failures
  steps?: JobStep[] };  // a job's card: every step it needed, plain words first

/** A step a background job was refused: what it is in plain words, the exact command, and whether a tap may allow it. */
export type JobStep = { words: string; raw: string; allowed: boolean };

/** Whether an "open" button's address may be opened: only an https page on GitHub (the server builds it from a checked
 *  name). "https://github.com/example/app/pull/49" -> true; "javascript:alert(1)" -> false; "http://github.com/x" -> false. */
export function opensSafely(url: string): boolean {
  return /^https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/(pull|issues)\/\d+$/.test(url);
}

/** A card's buttons in the order they show: the move, Done, then Later when the server sends it.
 *  {main: "Show the draft", other: "Done", later: "Later"} -> those three; no later (an older server) -> the first two. */
export function buttonsOf(need: Need): NeedAction[] {
  if (!need.later) return [need.main, need.other];
  return [need.main, need.other, need.later];
}

const ICON_COLOUR: Partial<Record<IconName, TileColor>> = {
  alert: "orange", rupee: "green", cal: "orange", heart: "pink", ticket: "violet", mail: "blue", bell: "yellow",
};

/** A card's tile colour from its icon: "rupee" -> "green", "alert" -> "orange"; an icon without one -> "ink". */
export function tileColour(icon: IconName): TileColor {
  return ICON_COLOUR[icon] ?? "ink";
}

/** The pill's tone: "Overdue" -> "warn"; any other date or amount -> "soft". */
export function badgeTone(badge: string): "warn" | "soft" {
  return badge === "Overdue" ? "warn" : "soft";
}

/** Where a chat button takes the app: "Show the draft for watch item mail:r1" -> "#chat?run=Show%20the%20draft…",
 * which Chat sends at once, as a card's button in chat does. */
export function chatRunHash(request: string): string {
  return `#chat?run=${encodeURIComponent(request)}`;
}

/** Something the watch did for a "Watch for" note and said was worth telling, with any file it made. */
export type WatchNote = { at: string; message: string; media: Pick<Media, "id" | "title" | "filename">[] };
