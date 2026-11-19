// Taps that land where the user meant. When a Pulse card leaves (or a refresh adds, removes or reorders cards), the
// next card moves up under the finger; a double tap, or a tap a moment late, would press that card's button. So for
// a short while after any card list on Pulse changes, every card button ignores taps. One guard for the whole screen:
// a job finishing in "On it" moves the cards under it too.
import { useLayoutEffect } from "react";

export const SETTLE_MS = 800;

export type TapGuard = { changed: () => void; ok: () => boolean };

export function createTapGuard(now: () => number = () => Date.now(), settleMs: number = SETTLE_MS): TapGuard {
  let changedAt = Number.NEGATIVE_INFINITY;
  return {
    changed() { changedAt = now(); },
    /**
     * Whether a tap counts: the cards have held still for the settle time.
     *   the list changed 300 ms ago -> false (the tap may be meant for a card that moved);  1 s ago -> true;
     *   never changed -> true
     */
    ok() { return now() - changedAt >= settleMs; },
  };
}

/** Pulse's one guard. */
export const pulseTaps = createTapGuard();

/** Tells the guard when a list's cards change: `key` is their refs in order ("loop:1 task:7"). Before the browser
 *  paints the new places, so no tap can land on them unguarded. A list that first appears counts as a change. */
export function useListChanged(key: string, guard: TapGuard = pulseTaps): void {
  useLayoutEffect(() => { guard.changed(); }, [key, guard]);
}
