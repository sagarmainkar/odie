import { dictate, speak as browserSpeak } from "./api";
import { meter } from "./mic";

let current: HTMLAudioElement | null = null;

/** Read text aloud with Odie's OpenAI voice; falls back to the phone's own voice if OpenAI isn't set up. Returns stop(). */
export function speak(text: string, onStart?: () => void, onEnd?: () => void, onPending?: () => void): () => void {
  stopSpeaking();
  let cancelled = false;
  const stop = () => { cancelled = true; stopSpeaking(); onEnd?.(); };
  onPending?.();  // local voices (Maya1) can take a while to prepare
  fetch("/api/tts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) })
    .then(async (r) => {
      if (cancelled) return;
      if (!r.ok) { browserSpeak(text, onStart, onEnd); return; }
      const url = URL.createObjectURL(await r.blob());
      const a = new Audio(url);
      current = a;
      a.onplay = () => onStart?.();
      a.onended = () => { URL.revokeObjectURL(url); if (current === a) current = null; onEnd?.(); };
      a.onerror = () => { onEnd?.(); };
      await a.play();
    })
    .catch(() => { if (!cancelled) browserSpeak(text, onStart, onEnd); });
  return stop;
}

export function isSpeaking(): boolean { return current !== null; }

export function stopSpeaking() {
  if (current) { current.pause(); current = null; }
  window.speechSynthesis?.cancel();
}

/** Record speech and transcribe it with OpenAI (gpt-4o-mini-transcribe). Returns stop(): call it to finish and transcribe.
 * Falls back to the browser's live dictation when recording isn't possible. */
export async function listen(onText: (t: string) => void, onState: (s: "recording" | "transcribing" | "idle") => void,
                             onLevel: (l: number) => void = () => {}, onError: (m: string) => void = () => {}): Promise<(() => void) | null> {
  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
    const stop = dictate(onText, () => onState("idle"));
    if (stop) onState("recording");
    return stop;
  }
  let stream: MediaStream;
  try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); } catch { return null; }
  const stopMeter = meter(stream, onLevel);
  const rec = new MediaRecorder(stream);
  const chunks: Blob[] = [];
  rec.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
  rec.onstop = async () => {
    stopMeter();
    stream.getTracks().forEach((t) => t.stop());
    onState("transcribing");
    try {
      const type = rec.mimeType || "audio/mp4";
      const ext = type.includes("webm") ? "webm" : type.includes("ogg") ? "ogg" : "mp4";
      const fd = new FormData(); fd.append("file", new Blob(chunks, { type }), `speech.${ext}`);
      const r = await fetch("/api/stt", { method: "POST", body: fd });
      if (r.ok) { const j = await r.json(); if (j.text) onText(j.text); }
      else onError(r.status === 503 ? "To dictate, add an OpenAI key in Settings, or use the 🎤 on your keyboard." : "Couldn't write that down. Try again.");
    } catch { onError("Couldn't write that down. Try again."); } finally { onState("idle"); }
  };
  rec.start();
  onState("recording");
  return () => { if (rec.state !== "inactive") rec.stop(); };
}
