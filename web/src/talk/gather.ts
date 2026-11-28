// When you have finished speaking. Silero calls speech over after a quarter of a second of quiet, so a breath in the
// middle of a sentence ends a piece of it. The gatherer keeps each piece's words and waits a little longer: speech
// starting again inside that wait joins the same turn; a wait that passes with nothing new sends the whole turn.
//   "There was no moon." … 0.7 s … "it was going to be a long night." … 0.9 s quiet
//     → one turn: "There was no moon. it was going to be a long night."

export const GATHER_MS = 900;

type Timers = { set: (run: () => void, ms: number) => number; clear: (id: number) => void };
const realTimers: Timers = { set: (run, ms) => window.setTimeout(run, ms), clear: (id) => window.clearTimeout(id) };

export class Gatherer {
  private pieces: string[] = [];
  private timer: number | null = null;
  private readonly timers: Timers;
  private readonly onTurn: (words: string) => void;

  constructor(onTurn: (words: string) => void, timers: Timers = realTimers) {
    this.onTurn = onTurn;
    this.timers = timers;
  }

  /** The words so far in this turn, as one line for the screen. */
  get words(): string {
    return this.pieces.join(" ");
  }

  /** Speech started again: the wait is off until this piece's words come. */
  speechStarted(): void {
    this.cancelWait();
  }

  /** A piece's final words: kept, and the wait (re)started. Empty words (a cough) keep the wait going if a turn
   *  is already gathering, and start nothing otherwise. */
  finalWords(text: string): void {
    const words = text.trim();
    if (words) this.pieces.push(words);
    if (this.pieces.length === 0) return;
    this.cancelWait();
    this.timer = this.timers.set(() => this.send(), GATHER_MS);
  }

  /** Drops whatever was gathered (the talk ended or Odie is about to answer). */
  reset(): void {
    this.cancelWait();
    this.pieces = [];
  }

  private send(): void {
    this.timer = null;
    const turn = this.words;
    this.pieces = [];
    if (turn) this.onTurn(turn);
  }

  private cancelWait(): void {
    if (this.timer !== null) this.timers.clear(this.timer);
    this.timer = null;
  }
}
