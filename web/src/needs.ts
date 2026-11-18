import type { IconName, TileColor } from "./components/Tile";
import type { Media } from "./media";

/** What a card's button does, decided by the server (odie/watch/needs.py). "later": put the card off until 09:00
 *  tomorrow (POST /api/needs_you/later with its ref). */
export type NeedAction = { label: string; action: "chat" | "dismiss" | "done_task" | "snooze_task" | "later"; value: string | number };

/** One card in a Pulse's "Needs you": a watch item from mail, or one of the user's own reminders. Every card has the
 *  same three buttons: its one move (main), Done (other) and Later (later; an older server sends no Later). */
export type Need = { ref: string; title: string; why: string; icon: IconName; badge: string; ask: string; main: NeedAction; other: NeedAction; later?: NeedAction };

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
