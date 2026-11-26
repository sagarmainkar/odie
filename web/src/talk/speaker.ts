// Talk's voice: each sentence goes to Odie's /api/tts as soon as it is known (two requests at a time), with the reply's
// tone, and the answers play back to back on one AudioContext, so one sentence runs into the next. `stop` cuts it all
// at once (the Interrupt button): nothing asked for before it is heard after it.

type Fetcher = (text: string, tone: string | null, signal: AbortSignal) => Promise<ArrayBuffer>;

/** Odie's own read-aloud route: the sentence and the reply's tone (Libra keeps it past the first sentence). */
export async function fetchSpeech(text: string, tone: string | null, signal: AbortSignal): Promise<ArrayBuffer> {
  const body: { text: string; tone?: string } = { text };
  if (tone) body.tone = tone;
  const reply = await fetch("/api/tts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal });
  if (!reply.ok) throw new Error(`speech ${reply.status}`);
  return reply.arrayBuffer();
}

const IN_FLIGHT = 2;

export class TalkSpeaker {
  private readonly context: AudioContext;
  private readonly fetcher: Fetcher;
  private waiting: { text: string; tone: string | null }[] = [];
  private fetching: { text: string; sound: Promise<ArrayBuffer | null>; abort: AbortController }[] = [];
  private playing: AudioBufferSourceNode[] = [];
  private nextStart = 0;
  private generation = 0;
  private draining = false;
  private quietHandlers: (() => void)[] = [];
  /** Told each sentence as it starts to be heard: the screen shows the words being said. */
  onSentence: (text: string) => void = () => {};
  /** Told true when the first sentence starts playing, false when the last has been heard (or the voice was cut). */
  onSpeaking: (speaking: boolean) => void = () => {};
  speaking = false;

  constructor(context: AudioContext, fetcher: Fetcher = fetchSpeech) {
    this.context = context;
    this.fetcher = fetcher;
  }

  /** Adds a sentence: its request starts when a slot is free, and it plays in its turn. */
  say(text: string, tone: string | null): void {
    this.waiting.push({ text, tone });
    this.startFetches();
    void this.drain();
  }

  /** Whether everything asked for has been heard: nothing waiting, fetching or playing. */
  get quiet(): boolean {
    return this.waiting.length === 0 && this.fetching.length === 0 && this.playing.length === 0;
  }

  /** Resolves once the voice falls quiet (at once when it already is). */
  whenQuiet(): Promise<void> {
    if (this.quiet) return Promise.resolve();
    return new Promise((resolve) => this.quietHandlers.push(resolve));
  }

  /** Cuts the voice now: the queue dropped, requests cancelled, sounds stopped. */
  stop(): void {
    this.generation += 1;
    this.waiting = [];
    for (const item of this.fetching) item.abort.abort();
    this.fetching = [];
    for (const source of this.playing) {
      try { source.stop(); } catch { /* already ended */ }
    }
    this.playing = [];
    this.nextStart = 0;
    this.draining = false;
    this.settle();
  }

  private startFetches(): void {
    while (this.fetching.length < IN_FLIGHT && this.waiting.length > 0) {
      const next = this.waiting.shift();
      if (!next) return;
      const abort = new AbortController();
      const sound = this.fetcher(next.text, next.tone, abort.signal).catch(() => null);  // a failed sentence is skipped
      this.fetching.push({ text: next.text, sound, abort });
    }
  }

  private async drain(): Promise<void> {
    if (this.draining) return;
    this.draining = true;
    const mine = this.generation;
    while (this.fetching.length > 0 && mine === this.generation) {
      const head = this.fetching[0];
      const bytes = await head.sound;
      if (mine !== this.generation) return;
      this.fetching.shift();
      this.startFetches();
      if (bytes) await this.play(bytes, head.text, mine);
    }
    if (mine === this.generation) this.draining = false;
    this.settle();
  }

  private async play(bytes: ArrayBuffer, text: string, mine: number): Promise<void> {
    let buffer: AudioBuffer;
    try { buffer = await this.context.decodeAudioData(bytes); } catch { return; }
    if (mine !== this.generation) return;
    const source = this.context.createBufferSource();
    source.buffer = buffer;
    source.connect(this.context.destination);
    const start = Math.max(this.context.currentTime + 0.02, this.nextStart);
    this.nextStart = start + buffer.duration;
    this.playing.push(source);
    source.onended = () => {
      this.playing = this.playing.filter((s) => s !== source);
      this.settle();
    };
    source.start(start);
    const wait = Math.max(0, (start - this.context.currentTime) * 1000);
    setTimeout(() => { if (mine === this.generation) this.onSentence(text); }, wait);
    if (!this.speaking) { this.speaking = true; this.onSpeaking(true); }
  }

  private settle(): void {
    if (!this.quiet) return;
    if (this.speaking) { this.speaking = false; this.onSpeaking(false); }
    const handlers = this.quietHandlers;
    this.quietHandlers = [];
    for (const resolve of handlers) resolve();
  }
}
