// The reminder curtain's small pure part: which notices are waiting, in what order, and how one leaves the queue.
// The component (components/ReminderCurtain.tsx) shows the first; the server (/api/reminders/pending and the
// "reminder" live event) is where they come from.
import type { Media } from "./media";

export type Notice = { id: number; text: string; kind: string; delivered_at?: string; ts?: number; media?: Media[] };

/**
 * Adds a notice unless it's already waiting (the same reminder can arrive twice: from the pending list on open and
 * from the live stream). Oldest stays first.
 *   [] + {id: 3} → [{id: 3}];  [{id: 3}] + {id: 3} → [{id: 3}];  [{id: 3}] + {id: 4} → [{id: 3}, {id: 4}]
 */
export function withNotice(queue: Notice[], n: Notice): Notice[] {
  if (queue.some((x) => x.id === n.id)) return queue;
  return [...queue, n];
}

/** The queue without one notice (answered with Snooze or Dismiss): [{id: 3}, {id: 4}] without 3 → [{id: 4}]. */
export function withoutNotice(queue: Notice[], id: number): Notice[] {
  return queue.filter((x) => x.id !== id);
}

/** The memo to play when a curtain shows: the spoken reminder, if the app is on screen and nothing else plays. */
export function memoToPlay(n: Notice, visible: boolean, somethingPlaying: boolean): string | null {
  if (!visible || somethingPlaying) return null;
  const memo = (n.media ?? []).find((m) => m.kind === "memo");
  return memo ? memo.id : null;
}

/**
 * The times a reminder can be put off to, as ISO strings the server's snooze takes; it rings again then.
 *   at 18:20 on 25 Oct -> "1 hour" 19:20, "3 hours" 21:20, "Tomorrow 9:00" 26 Oct 09:00
 *   at 00:30 on 26 Oct -> "Tomorrow 9:00" is 26 Oct 09:00 (before 5 am, "tomorrow" is the morning ahead);
 *   at 05:00 on 26 Oct -> 27 Oct 09:00
 */
export function snoozeChoices(now: Date): { label: string; until: string }[] {
  const hour = 60 * 60 * 1000;
  const smallHours = now.getHours() < 5;
  const daysAhead = smallHours ? 0 : 1;
  const tomorrowMorning = new Date(now.getFullYear(), now.getMonth(), now.getDate() + daysAhead, 9, 0);
  return [
    { label: "1 hour", until: new Date(now.getTime() + hour).toISOString() },
    { label: "3 hours", until: new Date(now.getTime() + 3 * hour).toISOString() },
    { label: "Tomorrow 9:00", until: tomorrowMorning.toISOString() },
  ];
}
