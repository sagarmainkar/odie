import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { hideVoiceMarkup } from "../blocks/voiceMarkup";
import { usePersona } from "../persona";
import { setTalking } from "../playing";
import { Gatherer } from "../talk/gather";
import { Hearing } from "../talk/hearing";
import { TalkSentences, toneOf } from "../talk/sentences";
import { canInterrupt, faceFor, type TalkPhase } from "../talk/phase";
import { TalkSpeaker } from "../talk/speaker";
import { Avatar } from "./Avatar";
import { SpeakingBars } from "./Orb";
import { Icon } from "./Tile";
import { Wash } from "./Wash";

const STATUS: Record<TalkPhase, string> = {
  connecting: "Getting ready", listening: "Listening", you: "Listening", thinking: "Thinking",
  speaking: "Speaking", error: "Talk stopped",
};

type Props = {
  audio: AudioContext;           // made in the tap that opened Talk (a phone lets audio start only there); closed here
  onClose: () => void;
  send: (text: string) => void;  // the chat's own send: the spoken words become a normal message in the thread
  replyId: number | null;        // the newest reply in the chat, and its words so far
  replyText: string;
  busy: boolean;                 // a reply is still being written
};

/** Talk on this Odie, kept simple: Odie listens (Silero hears you start and stop, Parakeet writes the words, both on
 *  the Mac), your words go to the chat as a message, the reply is read sentence by sentence in the chosen voice (Libra
 *  with its tone and sounds), and Odie listens again. While it speaks the mic is off; Interrupt stops the voice and
 *  listens at once. */
export function LocalTalk({ audio, onClose, send, replyId, replyText, busy }: Props) {
  const { name } = usePersona();
  const [phase, setPhase] = useState<TalkPhase>("connecting");
  const [youSaid, setYouSaid] = useState("");
  const [saying, setSaying] = useState("");
  const [error, setError] = useState("");
  const phaseRef = useRef<TalkPhase>("connecting");
  const hearing = useRef<Hearing | null>(null);
  const speaker = useRef<TalkSpeaker | null>(null);
  const turn = useRef<{ sentences: TalkSentences; after: number | null; hushed: boolean; done: boolean } | null>(null);
  const gatherer = useRef<Gatherer | null>(null);
  const latestReply = useRef<number | null>(replyId);
  latestReply.current = replyId;

  function moveTo(next: TalkPhase) {
    phaseRef.current = next;
    setPhase(next);
  }

  function fail(why: string) {
    setError(why);
    moveTo("error");
    hearing.current?.close();
    speaker.current?.stop();
  }

  async function listenAgain() {
    turn.current = null;
    gatherer.current?.reset();
    setSaying("");
    moveTo("listening");
    try { await hearing.current?.resume(); } catch { fail("I can't use the microphone. Allow it for this app."); }
  }

  // Start: a voice for replies and the ears, both on the AudioContext the tap that opened Talk made.
  useEffect(() => {
    setTalking(true);  // a spoken reminder waits while Talk is on
    const context = audio;
    void context.resume();
    const voice = new TalkSpeaker(context);
    voice.onSpeaking = (on) => { if (on && phaseRef.current === "thinking") moveTo("speaking"); };
    voice.onSentence = (sentence) => setSaying(hideVoiceMarkup(sentence));
    speaker.current = voice;
    const ears = new Hearing(context);
    hearing.current = ears;
    const gather = new Gatherer((words) => heard(words));
    gatherer.current = gather;
    ears.onClosed = (why) => { if (phaseRef.current !== "error") fail(why); };
    ears.onEvent = (event) => {
      const hearingNow = phaseRef.current === "listening" || phaseRef.current === "you";
      if (!hearingNow) return;
      if (event.type === "speech" && event.on) { gather.speechStarted(); moveTo("you"); }
      if (event.type === "words" && !event.final) setYouSaid(`${gather.words} ${event.text}`.trim());
      if (event.type === "words" && event.final) { gather.finalWords(event.text); setYouSaid(gather.words); }
      if (event.type === "error") fail("Odie couldn't hear that. Try again.");
    };
    (async () => {
      try {
        await ears.open();
        await listenAgain();
      } catch (e) {
        fail(e instanceof Error ? e.message : "Couldn't start listening.");
      }
    })();
    return () => {
      setTalking(false);
      gather.reset();
      ears.close();
      voice.stop();
      void context.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // What you said, once you had finished (the gatherer waited out your pauses): the mic is let go, the words go to the
  // chat, and the reply is awaited.
  function heard(text: string) {
    const words = text.trim();
    if (!words) return;
    if (phaseRef.current !== "you" && phaseRef.current !== "listening") return;
    hearing.current?.pause();
    setYouSaid(words);
    turn.current = { sentences: new TalkSentences(), after: latestReply.current, hushed: false, done: false };
    moveTo("thinking");
    send(words);
  }

  // The reply as it streams: each finished sentence is said; when it's all written and all said, Odie listens again.
  useEffect(() => {
    const now = turn.current;
    if (!now || now.hushed || now.done) return;
    if (replyId === null || replyId === now.after) return;  // still the reply before this question
    const tone = toneOf(replyText);
    const fresh = busy ? now.sentences.feed(replyText) : now.sentences.finish(replyText);
    for (const sentence of fresh) speaker.current?.say(sentence, tone);
    if (busy) return;
    now.done = true;
    void speaker.current?.whenQuiet().then(() => {
      if (turn.current === now && !now.hushed) void listenAgain();
    });
  }, [replyId, replyText, busy]);  // eslint-disable-line react-hooks/exhaustive-deps

  function interrupt() {
    void audio.resume();  // a tap: the phone lets audio go on again if it had stopped it
    const now = turn.current;
    if (now) now.hushed = true;  // the rest of this reply still arrives in the chat, but isn't said
    speaker.current?.stop();
    void listenAgain();
  }

  function end() {
    hearing.current?.close();
    speaker.current?.stop();
    onClose();
  }

  const caption = phase === "error" ? error : saying;
  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.24 }}
      className="fixed inset-0 z-50 isolate flex flex-col items-center text-center text-ink safe-top safe-bottom px-6" role="dialog" aria-label={`Talking with ${name}`}>
      <Wash />
      <div className="w-full flex items-center justify-between">
        <button onClick={end} aria-label="Back to chat" className="pill w-11 px-0"><Icon name="back" /></button>
        <span className="chip chip-soft">{name}</span>
        <span className="w-11" />
      </div>
      <div className="flex-1 w-full flex flex-col items-center justify-center">
        <div className="relative grid place-items-center">
          <span aria-hidden="true" className="absolute w-[330px] h-[330px] rounded-full blur-[60px] opacity-55 bg-[conic-gradient(from_0deg,#8fdcff,#b9a8ff,#ffb0dc,#ffe0a8,#8fdcff)] animate-[orb-spin_16s_linear_infinite]" />
          <Avatar state={faceFor(phase)} size={210} halo />
        </div>
        <div className="mt-11 h-5 text-ui font-bold text-muted flex items-center gap-2">
          {phase === "speaking" && <SpeakingBars />}{STATUS[phase]}
        </div>
        <div className="mt-4 min-h-[120px] max-w-[340px] flex flex-col items-center gap-2.5">
          <AnimatePresence mode="wait">
            <motion.div key={`${youSaid.slice(0, 12)}|${caption.slice(0, 20)}`} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="flex flex-col gap-2.5">
              {youSaid && <div className="text-title leading-[1.4] text-muted">{youSaid}</div>}
              {caption && <div className="text-display-sm leading-[1.4] font-medium tracking-[-0.015em]">{caption}</div>}
            </motion.div>
          </AnimatePresence>
        </div>
      </div>
      <div className="flex items-center gap-[18px] pb-6">
        {canInterrupt(phase) && (
          <button onClick={interrupt} aria-label="Interrupt" className="pill h-[60px] px-6 text-ui font-bold">
            <span className="w-3.5 h-3.5 rounded-[3px] bg-current" /> Interrupt
          </button>
        )}
        <button onClick={end} aria-label="End" className="pill w-[60px] h-[60px] px-0 !bg-[#f0605a] text-white !border-transparent">
          <Icon name="x" size={24} stroke={2.4} />
        </button>
      </div>
    </motion.div>
  );
}
