import { dictate } from "./api";
import { meter } from "./mic";
import { listen } from "./voice";

export { levelOf } from "./mic";

/** How the mic dictates: live text through OpenAI (a transcription-only realtime session), the phone's own speech
 *  recognition without a key, or a clear note when neither works. Never a silent mic. */
export type Mode = "live" | "phone" | "none";

export function pickMode({ dictation, phoneSpeech }: { dictation: boolean; phoneSpeech: boolean }): Mode {
  return dictation ? "live" : phoneSpeech ? "phone" : "none";
}

export function phoneSpeech(): boolean {
  return typeof window !== "undefined" && !!((window as any).webkitSpeechRecognition || (window as any).SpeechRecognition);
}

export const NO_DICTATION = "To dictate, add an OpenAI key in Settings, or use the 🎤 on your keyboard.";

/** The words so far: phrases in the order they began, each the model's final wording once it's done. */
export type Text = { order: string[]; words: Record<string, string> };

export const emptyText = (): Text => ({ order: [], words: {} });

type Ev = { type: string; item_id?: string; delta?: string; transcript?: string };

export function applyEvent(s: Text, ev: Ev): Text {
  const id = ev.item_id;
  if (!id) return s;
  const order = s.order.includes(id) ? s.order : [...s.order, id];
  if (ev.type === "conversation.item.input_audio_transcription.delta") return { order, words: { ...s.words, [id]: (s.words[id] ?? "") + (ev.delta ?? "") } };
  if (ev.type === "conversation.item.input_audio_transcription.completed") return { order, words: { ...s.words, [id]: (ev.transcript ?? s.words[id] ?? "").trim() } };
  return s;
}

export function textOf(s: Text): string {
  return s.order.map((id) => (s.words[id] ?? "").trim()).filter(Boolean).join(" ");
}

type Hooks = { onText: (t: string) => void; onLevel: (l: number) => void; onState: (s: "recording" | "transcribing" | "idle") => void; onError: (m: string) => void };

/** Live: the words appear as the user talks. Falls back to record-then-transcribe if the live session won't start. */
async function live(h: Hooks): Promise<(() => void) | null> {
  let stream: MediaStream;
  try { stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } }); } catch { return null; }
  const stopMeter = meter(stream, h.onLevel);
  let pc: RTCPeerConnection | null = null;
  const end = () => { stopMeter(); stream.getTracks().forEach((t) => t.stop()); pc?.close(); pc = null; h.onState("idle"); };
  try {
    const r = await fetch("/api/voice/dictation", { method: "POST" });
    if (!r.ok) throw new Error(`session ${r.status}`);
    const { client_secret } = await r.json();
    pc = new RTCPeerConnection();
    stream.getTracks().forEach((t) => pc!.addTrack(t, stream));
    const ch = pc.createDataChannel("oai-events");
    let text = emptyText();
    ch.onmessage = (e) => { try { text = applyEvent(text, JSON.parse(e.data)); h.onText(textOf(text)); } catch { /* not ours */ } };
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    const ans = await fetch("https://api.openai.com/v1/realtime/calls", {
      method: "POST", body: offer.sdp, headers: { Authorization: `Bearer ${client_secret}`, "Content-Type": "application/sdp" } });
    if (!ans.ok) throw new Error(`call ${ans.status}`);
    await pc.setRemoteDescription({ type: "answer", sdp: await ans.text() });
    h.onState("recording");
    // Stopping: the mic shows "writing it down" while the last phrase has a moment to arrive, then it's over.
    return () => { h.onState("transcribing"); setTimeout(end, 700); };
  } catch {
    end();
    return recorded(h);  // OpenAI is set up, but the live route failed: record, then transcribe, as before
  }
}

/** Record, then transcribe when the user stops (the way the mic always worked), with the wave while recording. */
async function recorded(h: Hooks): Promise<(() => void) | null> {
  return listen((t) => h.onText(t), (s) => h.onState(s), h.onLevel, (m) => h.onError(m));
}

/**
 * The hooks, with the text shut off once the mic is idle: after that, nothing the recogniser still sends can rewrite
 * what the user has started editing. Worked example: words arrive, the user taps stop, "idle" is reported, a late
 * "completed" event arrives -> it is dropped; the composer keeps what the user has.
 */
export function quietAfterIdle(h: Hooks): Hooks {
  let idle = false;
  return {
    ...h,
    onText: (t) => { if (!idle) h.onText(t); },
    onState: (s) => { if (s === "idle") idle = true; h.onState(s); },
  };
}

export async function startDictation(mode: Mode, hooks: Hooks): Promise<(() => void) | null> {
  const h = quietAfterIdle(hooks);
  if (mode === "live") return live(h);
  if (mode === "phone") {
    const stop = dictate(h.onText, () => h.onState("idle"));
    if (stop) h.onState("recording");
    else h.onError(NO_DICTATION);
    return stop;
  }
  h.onError(NO_DICTATION);
  return null;
}
