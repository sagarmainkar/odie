// Pulse (it replaced Today, 18 Nov 2026): each personality's own screen of what needs the user, what Odie is still on
// and what it closed today. Odie's Pulse keeps everything Today had; another personality's shows its own cards, and
// Odie's shows the others only as a count ("Mira: 2 waiting"). The server builds the cards (odie/watch/needs.py,
// odie/loops/cards.py); these are the words around them.

/** A loop Odie is still working on, under "Odie is on it". */
export type OnIt = { id: number; title: string; state: string; next: string };
/** A loop Odie closed today, with why, under "Done today" (each with Reopen). */
export type LoopDone = { id: number; title: string; why: string; closed: string };
/** Another personality with cards waiting, as Odie's Pulse counts them. */
export type Other = { id: string; name: string; waiting: number };

const STATE_WORDS: Record<string, string> = { new: "starting", working: "working on it", waiting: "waiting" };

/** One "Odie is on it" row's second line: the state in words, then what it waits for.
 *    {state: "waiting", next: "CI still running"} -> "waiting · CI still running"
 *    {state: "new", next: ""} -> "starting" */
export function onItLine(item: OnIt): string {
  const state = STATE_WORDS[item.state] ?? item.state;
  if (!item.next) return state;
  return `${state} · ${item.next}`;
}

/** Another personality's count on Odie's Pulse: {name: "Mira", waiting: 2} -> "Mira: 2 waiting". */
export function otherLine(other: Other): string {
  return `${other.name}: ${other.waiting} waiting`;
}

/** The Pulse heading's small line: everyday Odie's Pulse is the day ("Wednesday 18 November"); a personality's says
 *  whose it is.  ("", "Wednesday 18 November", "Odie") -> "Wednesday 18 November";
 *  ("abc", "Wednesday 18 November", "Mira") -> "Mira's Pulse · Wednesday 18 November" */
export function pulseKicker(pick: string, date: string, name: string): string {
  if (!pick) return date;
  return `${name}'s Pulse · ${date}`;
}

/** Whether a personality's Pulse asks the user to turn Proactive intelligence on: offered (it has its own inbox) and
 *  off. {offered: true, on: false} -> true; on -> false; not offered -> false; unknown (null) -> false. */
export function asksToTurnOn(state: { offered: boolean; on: boolean } | null | undefined): boolean {
  if (!state) return false;
  return state.offered && !state.on;
}
