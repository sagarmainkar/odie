/** Spoken reminders (Settings → Voice → Speak reminders): a reminder that arrives with a voice memo plays at once,
 * if Odie is open and nothing else is playing. From history, it never plays on its own. */
import type { Media } from "./media";

export function autoplayFor(e: { type: string; text?: string; media?: Media[] }, visible: boolean, somethingPlaying: boolean): string | null {
  if (e.type !== "message" || !visible || somethingPlaying) return null;
  const memo = (e.media ?? []).find((m) => m.kind === "memo");
  return memo ? memo.id : null;
}
