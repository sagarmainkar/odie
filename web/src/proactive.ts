// A personality's "Proactive intelligence" switch (odie/watch/owner.py on the server): its own 30-minute mail and
// calendar check, offered only when it has a mail or calendar app of its own, and off until the user turns it on.
import { withPickOf } from "./pick";

export type Proactive = { offered: boolean; on: boolean; apps: string[] };

/** The switch's address for whoever is picked: "abc" -> "/api/proactive?personality=abc". */
export function proactiveUrl(pick: string): string {
  return withPickOf("/api/proactive", pick, true);
}

/** Whether Settings shows the switch. Only for a personality (everyday Odie keeps its own watch), and only when the
 *  server offers it (an app of its own that reads mail or a calendar).
 *    ("abc", offered) -> true;  ("abc", not offered) -> false;  ("", offered) -> false;  still loading (null) -> false */
export function showsProactive(pick: string, state: Proactive | null): boolean {
  if (!pick || state === null) return false;
  return state.offered;
}

/** The words under the switch: on -> what it does now; off -> what turning it on would do.
 *    (on, ["work-mail"]) -> "Checks work-mail every 30 minutes and puts what needs you on its Pulse."
 *    (off, ["work-mail"]) -> "Off: it reads work-mail only when you ask in chat." */
export function proactiveSub(state: Proactive): string {
  const apps = state.apps.join(", ");
  if (state.on) return `Checks ${apps} every 30 minutes and puts what needs you on its Pulse.`;
  return `Off: it reads ${apps} only when you ask in chat.`;
}

/** Settings → Notifications: the one line about what an iPhone's lock screen shows. */
export const PREVIEWS_LINE = "On iPhone, Settings → Notifications → Show Previews → When Unlocked keeps what a push says off the lock screen.";
