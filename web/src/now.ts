// The Now list (proactive design §5, §17): five to seven lines of what matters to the user now, one list per
// personality, kept by the server (odie/loops/now.py) and written only by his tap here. Odie drafts the first one on
// request and proposes changes on Sundays (a card on Pulse: Accept, No, Edit).

/** Odie's proposed list, waiting for his answer. `first`: he had none yet ("Start your Now list?"). */
export type NowProposal = { id: number; lines: string[]; why: string; first?: boolean };
/** GET /api/now: his lines, Odie's proposal (or null), and how many lines the list may have. */
export type NowGot = { lines: string[]; proposal: NowProposal | null; most: number };

export const LINE_MOST = 120;

/** The lines as they would be saved: each trimmed, blanks left out. ["  Ship Odie ", "", "Run"] -> ["Ship Odie", "Run"]. */
export function cleanLines(lines: string[]): string[] {
  return lines.map((l) => l.replace(/\s+/g, " ").trim()).filter((l) => l.length > 0);
}

/** Whether Save can go: at most `most` lines with words, none over LINE_MOST characters. An empty list may be saved
 *  (it clears the list). 7 lines of 7 -> true; 8 -> false; one line of 121 characters -> false; [] -> true. */
export function saveReady(lines: string[], most: number): boolean {
  const kept = cleanLines(lines);
  return kept.length <= most && kept.every((l) => l.length <= LINE_MOST);
}

/** Whether another line may be added while editing: fewer than `most` lines on screen. 6 of 7 -> true; 7 of 7 -> false. */
export function canAdd(lines: string[], most: number): boolean {
  return lines.length < most;
}

/** The list with line `i` moved by `by` places (−1 up, +1 down); a move past either end changes nothing.
 *  (["a", "b", "c"], 2, -1) -> ["a", "c", "b"];  (["a", "b"], 0, -1) -> ["a", "b"] */
export function moveLine(lines: string[], i: number, by: number): string[] {
  const j = i + by;
  if (j < 0 || j >= lines.length) return lines;
  const out = [...lines];
  [out[i], out[j]] = [out[j], out[i]];
  return out;
}

/** The list with line `i` taken out: (["a", "b", "c"], 1) -> ["a", "c"]. */
export function withoutLine(lines: string[], i: number): string[] {
  return lines.filter((_, k) => k !== i);
}
