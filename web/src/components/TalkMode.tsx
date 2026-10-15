import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { SpeakingBars, type OrbState } from "./Orb";
import { Avatar } from "./Avatar";
import { Wash } from "./Wash";
import { Icon } from "./Tile";
import { usePersona } from "../persona";
import { setTalking } from "../playing";

type Line = { who: "you" | "odie"; text: string };
type Phase = "connecting" | "listening" | "you" | "thinking" | "speaking" | "error";

const STATUS: Record<Phase, string> = {
  connecting: "Connecting", listening: "Listening", you: "Listening", thinking: "Checking with Odie", speaking: "Speaking · tap to interrupt", error: "Couldn't connect",
};

/** Full-screen realtime conversation (OpenAI gpt-realtime over WebRTC). The voice model handles the talk; anything about
 * the user's world goes to Odie through the one tool, ask_brain, which the server runs as a normal turn. */
export function TalkMode({ onClose }: { onClose: () => void }) {
  useEffect(() => { setTalking(true); return () => setTalking(false); }, []);  // a spoken reminder waits while Talk is on
  const { name } = usePersona();
  const [phase, setPhase] = useState<Phase>("connecting");
  const [error, setError] = useState("");
  const [muted, setMuted] = useState(false);
  const [captions, setCaptions] = useState(true);
  const [lines, setLines] = useState<Line[]>([]);
  const [live, setLive] = useState("");
  const pc = useRef<RTCPeerConnection | null>(null);
  const mic = useRef<MediaStream | null>(null);
  const dc = useRef<RTCDataChannel | null>(null);
  const audio = useRef<HTMLAudioElement | null>(null);
  const linesRef = useRef<Line[]>([]);
  const mutedRef = useRef(false);
  const busy = useRef({ speaking: false, asking: false });
  const sawBuffer = useRef(false);  // half-duplex: the mic is closed while she talks or while Odie works

  function micOpen(open: boolean) {
    mic.current?.getAudioTracks().forEach((t) => { t.enabled = open && !mutedRef.current; });
  }
  function settle() { micOpen(!busy.current.speaking && !busy.current.asking); }
  function addLine(l: Line) { linesRef.current = [...linesRef.current, l]; setLines(linesRef.current); }

  useEffect(() => {
    let closed = false;
    (async () => {
      try {
        const r = await fetch("/api/voice/session", { method: "POST" });
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `HTTP ${r.status}`);
        const s = await r.json();
        const conn = new RTCPeerConnection();
        pc.current = conn;
        const el = audio.current!;
        conn.ontrack = (e) => { el.srcObject = e.streams[0]; void el.play().catch(() => {}); };
        const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
        if (closed) { stream.getTracks().forEach((t) => t.stop()); return; }
        mic.current = stream;
        stream.getTracks().forEach((t) => conn.addTrack(t, stream));
        const ch = conn.createDataChannel("oai-events");
        dc.current = ch;
        ch.onmessage = (m) => handle(JSON.parse(m.data));
        ch.onopen = () => setPhase("listening");
        const offer = await conn.createOffer();
        await conn.setLocalDescription(offer);
        const ans = await fetch("https://api.openai.com/v1/realtime/calls", {
          method: "POST", body: offer.sdp, headers: { Authorization: `Bearer ${s.client_secret}`, "Content-Type": "application/sdp" },
        });
        if (!ans.ok) throw new Error(`OpenAI said ${ans.status}`);
        await conn.setRemoteDescription({ type: "answer", sdp: await ans.text() });
      } catch (e) {
        setError((e as Error).message); setPhase("error");
      }
    })();
    return () => { closed = true; saveTranscript(); hangUp(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function saveTranscript() {
    const lines = linesRef.current;
    linesRef.current = [];
    if (lines.length) void fetch("/api/voice/transcript", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ lines }), keepalive: true });
  }

  function interrupt() {
    // Tap her face: stop talking now and listen.
    if (!busy.current.speaking) return;
    send({ type: "response.cancel" });
    send({ type: "output_audio_buffer.clear" });
    busy.current.speaking = false; setPhase("listening"); settle();
  }

  function hangUp() {
    dc.current?.close();
    pc.current?.getSenders().forEach((s) => s.track?.stop());
    pc.current?.close();
    mic.current?.getTracks().forEach((t) => t.stop());
    pc.current = null; dc.current = null; mic.current = null;
  }

  function send(ev: object) { if (dc.current?.readyState === "open") dc.current.send(JSON.stringify(ev)); }

  async function handle(ev: any) {
    switch (ev.type) {
      case "input_audio_buffer.speech_started": setPhase("you"); setLive(""); break;
      case "conversation.item.input_audio_transcription.completed":
        if (ev.transcript?.trim()) addLine({ who: "you", text: ev.transcript.trim() });
        break;
      case "output_audio_buffer.started":
        sawBuffer.current = true; busy.current.speaking = true; settle(); setPhase("speaking"); break;
      case "response.done":
        // Safety net: if the audio-buffer events never come, don't leave the mic closed.
        if (!sawBuffer.current) { busy.current.speaking = false; settle(); setPhase(busy.current.asking ? "thinking" : "listening"); }
        break;
      case "response.output_audio_transcript.delta": case "response.audio_transcript.delta":
        busy.current.speaking = true; settle(); setPhase("speaking"); setLive((t) => t + (ev.delta || "")); break;
      case "response.output_audio_transcript.done": case "response.audio_transcript.done":
        if (ev.transcript?.trim()) addLine({ who: "odie", text: ev.transcript.trim() });
        setLive(""); break;
      case "output_audio_buffer.stopped": case "output_audio_buffer.cleared":
        busy.current.speaking = false; settle();
        setPhase(busy.current.asking ? "thinking" : "listening"); break;
      case "response.function_call_arguments.done": {
        busy.current.asking = true; settle();
        setPhase("thinking");
        let question = "";
        try { question = JSON.parse(ev.arguments || "{}").question || ""; } catch { /* keep empty */ }
        let output = "I couldn't reach my own brain just now.";
        try {
          const r = await fetch("/api/voice/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question }) });
          if (r.ok) output = (await r.json()).text;
        } catch { /* keep fallback */ }
        send({ type: "conversation.item.create", item: { type: "function_call_output", call_id: ev.call_id, output } });
        send({ type: "response.create" });
        busy.current.asking = false; settle();
        break;
      }
      case "error": setError(ev.error?.message || "Something went wrong"); break;
    }
  }

  function toggleMute() {
    const next = !muted;
    mutedRef.current = next; setMuted(next); settle();
  }

  const orb: OrbState = phase === "speaking" ? "speaking" : phase === "thinking" ? "thinking" : phase === "you" ? "listening" : "idle";
  const last = live || [...lines].reverse().find((l) => l.who === "odie")?.text || "";
  const lastYou = [...lines].reverse().find((l) => l.who === "you")?.text || "";

  const end = () => { saveTranscript(); hangUp(); onClose(); };
  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.24 }}
      className="fixed inset-0 z-50 isolate flex flex-col items-center text-center text-ink safe-top safe-bottom px-6" role="dialog" aria-label={`Talking with ${name}`}>
      <Wash />
      <audio ref={audio} autoPlay playsInline />
      <div className="w-full flex items-center justify-between">
        <button onClick={end} aria-label="Back to chat" className="pill w-11 px-0"><Icon name="back" /></button>
        <span className="chip chip-soft">{name}</span>
        <span className="w-11" />
      </div>
      <div className="flex-1 w-full flex flex-col items-center justify-center">
        <div className="relative grid place-items-center">
          <span aria-hidden="true" className="absolute w-[330px] h-[330px] rounded-full blur-[60px] opacity-55 bg-[conic-gradient(from_0deg,#8fdcff,#b9a8ff,#ffb0dc,#ffe0a8,#8fdcff)] animate-[orb-spin_16s_linear_infinite]" />
          <motion.button type="button" onClick={interrupt} aria-label={phase === "speaking" ? "Interrupt" : name} className="relative">
            <Avatar state={orb} size={210} halo />
          </motion.button>
        </div>
        <div className="mt-11 h-5 text-[14px] font-bold text-muted flex items-center gap-2">{phase === "speaking" && !muted && <SpeakingBars />}{muted ? "Muted" : STATUS[phase]}</div>
        <div className="mt-4 min-h-[120px] max-w-[340px] flex flex-col items-center gap-2.5">
          <AnimatePresence mode="wait">
            {phase === "error" ? (
              <motion.div key="err" initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="text-[16px] leading-6">{error || "Couldn't connect."}</motion.div>
            ) : captions ? (
              <motion.div key={last.slice(0, 20) + lastYou.slice(0, 10)} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="flex flex-col gap-2.5">
                {lastYou && <div className="text-[18px] leading-[1.4] text-muted">{lastYou}</div>}
                {last && <div className="text-[23px] leading-[1.4] font-medium tracking-[-0.015em]">{last}</div>}
              </motion.div>
            ) : null}
          </AnimatePresence>
        </div>
      </div>
      <div className="flex items-center gap-[18px] pb-6">
        <button onClick={toggleMute} aria-label={muted ? "Unmute" : "Mute"} className={`pill w-[60px] h-[60px] px-0 ${muted ? "pill-solid" : ""}`}>
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            {muted ? <path d="M9 9v3a3 3 0 0 0 5.1 2.1M15 9.3V5a3 3 0 0 0-5.9-.7M19 11a7 7 0 0 1-.6 2.8M5 11a7 7 0 0 0 11 5.7M12 18v3M3 3l18 18" />
              : <><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></>}
          </svg>
        </button>
        <button onClick={end} aria-label="End" className="pill w-[60px] h-[60px] px-0 !bg-[#f0605a] text-white !border-transparent">
          <Icon name="x" size={24} stroke={2.4} />
        </button>
        <button onClick={() => setCaptions((v) => !v)} aria-label={captions ? "Hide captions" : "Show captions"} className={`pill w-[60px] h-[60px] px-0 ${captions ? "" : "pill-solid"}`}>
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M4 6h16M4 12h10M4 18h7" /></svg>
        </button>
      </div>
    </motion.div>
  );
}
