/** How loud the voice is right now, 0 to 1, from the analyser's waveform bytes (128 is silence). */
export function levelOf(samples: Uint8Array): number {
  if (!samples.length) return 0;
  let sum = 0;
  for (const v of samples) sum += ((v - 128) / 128) ** 2;
  return Math.min(1, Math.sqrt(sum / samples.length) * 1.4);
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
  const tick = () => { an.getByteTimeDomainData(buf); onLevel(levelOf(buf)); raf = requestAnimationFrame(tick); };
  tick();
  return () => { cancelAnimationFrame(raf); onLevel(0); void ctx.close(); };
}
