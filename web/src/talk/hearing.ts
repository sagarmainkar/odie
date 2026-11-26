// Talk's ears: the microphone, turned into 16 kHz PCM (pcm.ts), streamed to Odie's /api/talk/listen, which hands it
// to Silero VAD and Parakeet on the Mac and sends back when speech starts and stops and what was said.
//   {"type": "ready"}  {"type": "speech", "on": true}  {"type": "words", "text": "what is", "final": false}
//   {"type": "speech", "on": false}  {"type": "words", "text": "what is the weather", "final": true}
// While Odie speaks the microphone is let go (`pause`), so it never hears itself and the phone keeps its loudspeaker;
// `resume` takes it again.
import { Resampler } from "./pcm";

export type HearingEvent =
  | { type: "ready" }
  | { type: "speech"; on: boolean }
  | { type: "words"; text: string; final: boolean }
  | { type: "error"; text?: string };

/** Why the ears closed, in words for the screen: Odie's 4503 says its own voice server can't hear here. */
export function closedBecause(code: number, reason: string): string {
  if (code === 4503) return reason || "Odie's listening isn't running on the Mac.";
  if (code === 1008 || code === 4401) return "This phone isn't paired with Odie.";
  return "Lost the connection to Odie.";
}

/** The listening address on the same host as the app: https → wss. */
export function listenUrl(location: { protocol: string; host: string }): string {
  const scheme = location.protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${location.host}/api/talk/listen`;
}

const FRAME = 512;  // 32 ms at 16 kHz: Silero's chunk, so nothing waits for a fuller frame

export class Hearing {
  private socket: WebSocket | null = null;
  private stream: MediaStream | null = null;
  private readonly context: AudioContext;
  private node: ScriptProcessorNode | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private pending: number[] = [];
  /** Every event from the ears, in order. */
  onEvent: (event: HearingEvent) => void = () => {};
  /** The ears closed (Odie stopped, the connection dropped): why, in words. */
  onClosed: (why: string) => void = () => {};
  /** How loud the microphone is now, 0..1, for the face. */
  onLevel: (level: number) => void = () => {};

  /** `context` is Talk's one AudioContext, made in the tap that opened Talk: a phone only lets audio start there, so
   *  the same one is used every time the microphone is taken again. */
  constructor(context: AudioContext) {
    this.context = context;
  }

  /** Opens the socket and waits for Odie's ears to be ready (the voice server may take a few seconds to start). */
  async open(): Promise<void> {
    const socket = new WebSocket(listenUrl(location));
    socket.binaryType = "arraybuffer";
    this.socket = socket;
    await new Promise<void>((resolve, reject) => {
      socket.onmessage = (message) => {
        const event = JSON.parse(String(message.data)) as HearingEvent;
        if (event.type === "ready") resolve();
        this.onEvent(event);
      };
      socket.onclose = (closed) => {
        const why = closedBecause(closed.code, closed.reason);
        reject(new Error(why));
        this.onClosed(why);
      };
    });
  }

  /** Takes the microphone and starts sending what it hears. */
  async resume(): Promise<void> {
    if (this.stream) return;
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    this.stream = stream;
    const context = this.context;
    void context.resume();
    const resampler = new Resampler(context.sampleRate);
    const source = context.createMediaStreamSource(stream);
    const node = context.createScriptProcessor(2048, 1, 1);
    node.onaudioprocess = (e) => {
      const input = e.inputBuffer.getChannelData(0);
      this.onLevel(levelOf(input));
      this.send(resampler.push(input));
    };
    source.connect(node);
    node.connect(context.destination);  // a script node only runs while connected; it writes nothing, so it is silent
    this.node = node;
    this.source = source;
  }

  /** Lets the microphone go (Odie is about to speak): nothing is sent until `resume`. */
  pause(): void {
    this.source?.disconnect();
    this.source = null;
    this.node?.disconnect();
    this.node = null;
    for (const track of this.stream?.getTracks() ?? []) track.stop();
    this.stream = null;
    this.pending = [];
    this.onLevel(0);
  }

  /** Ends the talk: the microphone let go and the socket closed after telling the ears it's over. */
  close(): void {
    this.pause();
    const socket = this.socket;
    this.socket = null;
    if (!socket) return;
    socket.onclose = null;
    if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "end" }));
    socket.close();
  }

  private send(samples: Int16Array): void {
    for (const sample of samples) this.pending.push(sample);
    const socket = this.socket;
    while (this.pending.length >= FRAME) {
      const frame = Int16Array.from(this.pending.splice(0, FRAME));
      if (socket?.readyState === WebSocket.OPEN) socket.send(frame.buffer);
    }
  }
}

/** A rough loudness of some samples, 0..1, for the face to swell with: the RMS, scaled up and capped. */
export function levelOf(samples: Float32Array): number {
  let sum = 0;
  for (const sample of samples) sum += sample * sample;
  const rms = Math.sqrt(sum / Math.max(1, samples.length));
  return Math.min(1, rms * 6);
}

/** Talk's AudioContext, made and started inside the tap that opens Talk: a phone lets audio start only in a tap, and
 *  this one context serves the microphone and the voice for the whole talk. */
export function openTalkAudio(): AudioContext {
  const context = new AudioContext();
  void context.resume();
  return context;
}
