// The digests and Quiet rules on Pulse (proactive design §8, phase 5). The server builds them (odie/loops/digest.py,
// odie/loops/quiet.py, odie/loops/learn.py); these are their shapes and the words around them.

/** A card that is a digest line instead of a card (a kind he quieted or rarely acts on), with Done. */
export type DigestLine = { id: number; title: string };
/** One change the evening review made, with Undo. */
export type ReviewChange = { id: number; words: string };
/** GET /api/digest: today's evening digest (until Got it), "while you were away" after 3+ hours away, or null. */
export type Digest = { kind: "evening" | "away"; title: string; text: string; at: string; quiet: DigestLine[];
  held: string[]; changes: ReviewChange[] };

/** His Quiet rule, in the words the server wrote (deletable). */
export type QuietRule = { id: number; text: string; kind: string; sender: string; at: string };
/** A kind Odie learned to put in the digest (with Undo). */
export type Learned = { id: number; kind: string; acted: number; of: number; at: string };
/** GET /api/quiet. */
export type QuietGot = { rules: QuietRule[]; learned: Learned[] };

/** Whether a digest has anything to show: words, a digest line, something held back or a change to undo.
 *  {text: "1 needs you: …"} -> true; all empty -> false; null -> false. */
export function digestShows(d: Digest | null | undefined): boolean {
  if (!d) return false;
  return !!d.text || d.quiet.length > 0 || d.held.length > 0 || d.changes.length > 0;
}

/** A learned kind in his words: {kind: "promo", acted: 0, of: 6} -> "promo: in the evening digest (you acted on 0 of 6)". */
export function learnedLine(l: Learned): string {
  return `${l.kind}: in the evening digest (you acted on ${l.acted} of ${l.of})`;
}

/** Whether Pulse's Quiet section shows: he has a rule, or Odie learned a kind. */
export function quietShows(got: QuietGot | null): boolean {
  if (!got) return false;
  return got.rules.length > 0 || got.learned.length > 0;
}

/** The loop a card's ref names, for noting the tap on its move: "loop:12" -> 12; "task:3", "loop:x" -> null. */
export function loopOf(ref: string): number | null {
  const m = /^loop:(\d+)$/.exec(ref);
  if (!m) return null;
  return Number(m[1]);
}
