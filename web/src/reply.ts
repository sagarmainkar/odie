/** Has the turn sent at `sentAt` produced something in history yet: a reply, or an approval card it stopped for?
 * (A turn that pauses for a tap while the app is in the background leaves a card, not a reply.) */
export function replyArrived(items: { role: string; ts?: number; text?: string; media?: unknown[] }[], sentAt: number): boolean {
  const last = items[items.length - 1];
  if (!last || (last.ts ?? 0) < sentAt) return false;
  if (last.role === "approval") return true;
  // A step still running (a podcast being recorded) is an Odie item with no text and nothing made yet: not the reply.
  return last.role === "odie" && !(last.text === "" && !last.media?.length);
}

/** Back on screen with an answer still "streaming": iOS often leaves a suspended stream hanging, not closed. Quiet for
 * this long means it's stuck; drop it and fetch the saved answer instead. */
export const STALL_MS = 4000;
export function streamStalled(inFlight: boolean, lastEventAt: number, now: number, ms = STALL_MS): boolean {
  return inFlight && now - lastEventAt > ms;
}

/** After Approve (or an answer) the turn resumes on the server; it's finished once the outcome is saved on the card.
 * The live stream also announces it, but on iOS that stream can drop, so Chat checks the card itself. */
export function tapFinished(a: { status: string; result_text?: string | null }): boolean {
  return a.status === "expired" || (a.result_text !== null && a.result_text !== undefined);
}
