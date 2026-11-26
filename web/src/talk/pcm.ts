// The phone's microphone runs at its own rate (48 kHz, or 44.1 kHz); Odie's hearing (Silero VAD and Parakeet on the
// Mac, behind /api/talk/listen) takes 16 kHz 16-bit mono. This turns one into the other, piece by piece, as the
// microphone hands its samples over.

export const HEARING_RATE = 16000;

/** Float samples (-1..1) to 16-bit integers, clipped:  0.5 → 16383;  -1 → -32767;  1.7 → 32767. */
export function toInt16(sample: number): number {
  const clipped = Math.max(-1, Math.min(1, sample));
  return Math.round(clipped * 32767);
}

/**
 * Turns the microphone's samples into 16 kHz 16-bit PCM, one piece at a time, by linear interpolation. Where the
 * last piece stopped between two output samples is carried over, so pieces join without clicks.
 *   at 48 kHz, 4800 samples in → 1600 out;  at 16 kHz, 512 in → the same 512 (as integers)
 */
export class Resampler {
  private readonly step: number;  // input samples per output sample: 3 at 48 kHz
  private position = 0;           // where the next output sample falls, counted from the start of the next piece
  private previous = 0;           // the last input sample of the piece before, for a position that starts behind 0

  constructor(inputRate: number) {
    this.step = inputRate / HEARING_RATE;
  }

  push(input: Float32Array): Int16Array {
    const out: number[] = [];
    const last = input.length - 1;
    let at = this.position;
    while (at <= last) {
      const left = Math.floor(at);
      const fraction = at - left;
      // a position just before this piece (-0.5) sits between the last piece's end and this piece's start
      const before = left < 0 ? this.previous : input[left];
      const after = input[Math.min(left + 1, last)];
      out.push(toInt16(before + (after - before) * fraction));
      at += this.step;
    }
    this.position = at - input.length;
    if (input.length > 0) this.previous = input[input.length - 1];
    return Int16Array.from(out);
  }
}
