/** How loud the voice is right now, 0 to 1, from the analyser's waveform bytes (128 is silence). A phone's voice is
 *  quiet to the meter (noise suppression is on), so the loudness goes through a square root, closer to how ears hear
 *  it: silence -> 0; a soft voice (samples ±3 around 128) -> about 0.3; normal speech (±13) -> about 0.64; loud -> 1. */
export function levelOf(samples: Uint8Array): number {
  if (!samples.length) return 0;
  let sum = 0;
  for (const v of samples) sum += ((v - 128) / 128) ** 2;
  const loudness = Math.sqrt(sum / samples.length);
  return Math.min(1, Math.sqrt(loudness * 4));
}

const RISE = 0.6;   // how far toward a louder level the wave moves in one frame
const FALL = 0.12;  // and toward a quieter one: slower, so a pause between words doesn't flicker

/** The level shown, one frame on: it rises quickly with the voice and falls back slowly.
 *  shown 0, heard 1 -> 0.6 (a word starts); shown 1, heard 0 -> 0.88 (a pause); shown 0.4, heard 0.4 -> 0.4. */
export function smoothLevel(shown: number, heard: number): number {
  const step = heard > shown ? RISE : FALL;
  return shown + (heard - shown) * step;
}

/** Read the microphone's level on every frame (the wave while dictating). Returns stop(). */
export function meter(stream: MediaStream, onLevel: (l: number) => void): () => void {
  const Ctx = (window as any).AudioContext || (window as any).webkitAudioContext;
  if (!Ctx) return () => {};
  const ctx = new Ctx();
  const an = ctx.createAnalyser();
  an.fftSize = 512;
  ctx.createMediaStreamSource(stream).connect(an);
  const buf = new Uint8Array(an.fftSize);
  let raf = 0;
  let shown = 0;
  const tick = () => {
    an.getByteTimeDomainData(buf);
    shown = smoothLevel(shown, levelOf(buf));
    onLevel(shown);
    raf = requestAnimationFrame(tick);
  };
  tick();
  return () => { cancelAnimationFrame(raf); onLevel(0); void ctx.close(); };
}
