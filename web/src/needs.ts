import type { IconName, TileColor } from "./components/Tile";

/** What a card's button does, decided by the server (odie/watch/needs.py). */
export type NeedAction = { label: string; action: "chat" | "dismiss" | "done_task" | "snooze_task"; value: string | number };

/** One card in Today's "Needs you": a watch item from mail, or one of the user's own reminders. */
export type Need = { ref: string; title: string; why: string; icon: IconName; badge: string; ask: string; main: NeedAction; other: NeedAction };

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

/** Where a chat button takes the app: "Show the draft for desk item mail:r1" -> "#chat?run=Show%20the%20draft…",
 * which Chat sends at once, as a card's button in chat does. */
export function chatRunHash(request: string): string {
  return `#chat?run=${encodeURIComponent(request)}`;
}
