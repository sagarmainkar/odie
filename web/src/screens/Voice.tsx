import { motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { getJSON } from "../api";
import { AnotherVoice } from "../components/AnotherVoice";
import { LibraSettings } from "../components/LibraSettings";
import { Switch } from "../components/Switch";
import { engineLine, previewUrl, showLibra, voiceGroups, voiceSection, withPhononVoices, type PhononAnswer, type VoiceInfo } from "../voiceSettings";

/** One part of the screen: a short label, then a glass card (the label is left out when there is none). */
function Part({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      {title && <div className="section-label text-small leading-5 font-bold text-muted px-1.5">{title}</div>}
      <div className="glass rounded-card p-3 flex flex-col gap-3">{children}</div>
    </section>
  );
}

/** Settings → Voice: the read-aloud engine, its voices (with a preview each), Phonon's "Another voice" and Speak
 *  reminders. It used to be a section inside Settings; it moved here unchanged, so Settings stays short. */
export function Voice() {
  const [v, setV] = useState<VoiceInfo | null>(null);
  const [playing, setPlaying] = useState<string | null>(null);
  const audio = useRef<HTMLAudioElement | null>(null);
  const load = () => getJSON<VoiceInfo>("/api/voice").then(setV).catch(() => {});
  useEffect(() => { load(); return () => audio.current?.pause(); }, []);
  function play(engine: string, id: string, tone?: string, speed?: string) {
    audio.current?.pause();
    const key = tone ? `${engine}/${id}/${tone}` : `${engine}/${id}`;
    if (playing === key) { setPlaying(null); return; }
    const a = new Audio(previewUrl(engine, id, tone, speed));
    audio.current = a; setPlaying(key);
    a.onended = () => setPlaying(null); a.onerror = () => setPlaying(null);
    void a.play().catch(() => setPlaying(null));
  }
  function kept(answer: PhononAnswer) {
    setV((x) => (x ? withPhononVoices(x, answer) : x));
    play("phonon", answer.voice);  // the line the check spoke is the new voice's preview
  }
  async function forget(voiceId: string) {
    const r = await fetch(`/api/voice/phonon/voices/${encodeURIComponent(voiceId)}`, { method: "DELETE" });
    if (r.ok) { const answer = await r.json() as PhononAnswer; setV((x) => (x ? withPhononVoices(x, answer) : x)); }
  }
  async function save(body: { engine?: string; voice?: string; reminders_spoken?: boolean }) {
    const r = await fetch("/api/voice", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (r.ok) { const j = await r.json(); setV((x) => (x ? { ...x, engine: j.engine, voice: j.voice, reminders_spoken: j.reminders_spoken } : x)); }
  }
  /** Libra's tone or address: saved, then the whole screen read again (a new address may start or stop answering).
   *  Null when saved, else the server's reason (a bad address). */
  async function saveLibra(body: { libra_style?: string; libra_url?: string; libra_speed?: string }): Promise<string | null> {
    const r = await fetch("/api/voice", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!r.ok) {
      const answer = await r.json().catch(() => ({}));
      return String(answer?.detail || "That couldn't be saved.");
    }
    await load();
    return null;
  }

  return (
    <div className="h-full overflow-y-auto no-scrollbar px-[18px] safe-top flex flex-col gap-6 pb-6">
      <div className="flex items-center gap-3">
        <a href="#settings" aria-label="Back" className="pill w-11 px-0">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 6l-6 6 6 6" /></svg>
        </a>
        <div className="text-heading font-bold tracking-[-0.015em]">Voice</div>
      </div>
      {v && <VoiceBody v={v} playing={playing} play={play} kept={kept} forget={(id) => void forget(id)} save={(body) => void save(body)} saveLibra={saveLibra} />}
    </div>
  );
}

type BodyProps = {
  v: VoiceInfo; playing: string | null; play: (engine: string, id: string, tone?: string, speed?: string) => void; kept: (answer: PhononAnswer) => void;
  forget: (voiceId: string) => void; save: (body: { engine?: string; voice?: string; reminders_spoken?: boolean }) => void;
  saveLibra: (body: { libra_style?: string; libra_url?: string; libra_speed?: string }) => Promise<string | null>;
};

function VoiceBody({ v, playing, play, kept, forget, save, saveLibra }: BodyProps) {
  const shown = voiceSection(v);  // no engine at all: one plain line, and nothing below reads an engine that isn't there
  // Odie's own voice needs Apple Silicon; on an Intel Mac the server offers no local engine and says so here.
  const noLocal = v.local_voice === false;
  // which Libra tone's preview is playing now, for its button's spinner: "libra/sofia/wry" -> "wry"
  const libraPrefix = `libra/${v.voice}/`;
  const libraPlaying = playing?.startsWith(libraPrefix) ? playing.slice(libraPrefix.length) : null;
  const about = (
    <div className="text-small leading-[18px] text-muted px-1">
      Read-aloud (the speaker under each reply).{" "}
      {noLocal && <>Odie's own voice (Kokoro) needs Apple Silicon, so it isn't offered on this Mac.{" "}</>}
      {v.engines.some((e) => e.id === "openai") ? <>With your OpenAI key: its voices, and dictation that writes as you speak.</> : <>Add an OpenAI key in Providers for OpenAI voices and live dictation.</>}
    </div>
  );
  if (!shown.picker) {
    // No engine at all (the voice worker off, no OpenAI key): the phone's own voice still reads replies.
    return (
      <Part>
        {about}
        <div className="text-small leading-[18px] text-muted px-1">{shown.note} Until then, replies are read with the browser's own voice.</div>
      </Part>
    );
  }
  const eng = shown.engine;
  const line = engineLine(eng);  // on this computer or not, and what to do when it can't speak (Phonon: ollama pull)
  const pillTone = line.pill === "on this computer" ? "chip-good" : "chip-warn";
  return (
    <>
      <Part>
        {about}
        <div className="bg-well rounded-control p-1 flex gap-1" role="radiogroup" aria-label="Read-aloud engine">
          {v.engines.map((e) => (
            <button key={e.id} role="radio" aria-checked={e.id === v.engine} disabled={!e.available} onClick={() => save({ engine: e.id })}
              className={`relative flex-1 h-11 rounded-inner text-ui font-medium disabled:opacity-40 ${e.id === v.engine ? "text-ink" : "text-muted"}`}>
              {e.id === v.engine && <motion.span layoutId="engine-seg" transition={{ duration: 0.2 }} className="absolute inset-0 rounded-inner bg-surface" style={{ boxShadow: "var(--t-shadow-card)" }} />}
              <span className="relative">{e.label}</span>
            </button>
          ))}
        </div>
        <div className="text-small leading-[18px] px-1 flex items-start gap-2">
          {line.pill && <span className={`chip shrink-0 ${pillTone}`}>{line.pill}</span>}
          <span className="text-muted">{line.text}</span>
        </div>
      </Part>

      {voiceGroups(eng).map((g) => (
        <Part key={g.key} title={g.title || undefined}>
          <div className="grid grid-cols-2 gap-2">
            {g.voices.map((x) => {
              const on = x.id === v.voice;
              const key = `${eng.id}/${x.id}`;
              return (
                <div key={x.id} className={`flex items-center gap-1 rounded-control border pl-3 pr-1 min-h-12 ${on ? "border-ember-text bg-ember-tint" : "border-line"}`}>
                  <button onClick={() => { save({ voice: x.id }); play(eng.id, x.id); }} className="flex-1 text-left py-1.5 min-w-0">
                    <span className={`block text-body leading-5 ${on ? "font-semibold text-ember-text" : ""}`}>{x.label}</span>
                    {x.note && <span className="block text-caption leading-4 text-dim line-clamp-2">{x.note}</span>}
                  </button>
                  <button onClick={() => play(eng.id, x.id)} aria-label={`Hear ${x.label}`} className="w-10 h-10 rounded-full flex items-center justify-center text-muted shrink-0">
                    {playing === key ? <span className="spinner" /> : <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z" /></svg>}
                  </button>
                  {x.kept && <button onClick={() => forget(x.id)} aria-label={`Remove ${x.label}`} className="w-8 h-10 flex items-center justify-center text-dim shrink-0">×</button>}
                </div>
              );
            })}
          </div>
        </Part>
      ))}

      {eng.id === "phonon" && eng.available && <Part title="Another voice"><AnotherVoice onKept={kept} /></Part>}
      {v.libra && showLibra(v, eng.id) && <LibraSettings key={v.libra.url} libra={v.libra} chosen={eng.id === "libra"} save={saveLibra}
        hear={(tone, speed) => play("libra", v.voice, tone || "cheerful", speed)} playing={libraPlaying} />}
      {eng.id === "maya1" && <div className="text-caption leading-4 text-muted px-1.5 -mt-3">The first preview loads Maya1 (about half a minute). Replies are read with laughs, sighs and other expressions where they fit.</div>}

      <Part title="Reminders">
        <div className="flex items-start gap-3 px-1">
          <div className="flex-1 min-w-0">
            <div className="text-ui font-medium">Speak reminders</div>
            <div className="text-small leading-[18px] text-muted">{eng.available
              ? "Each reminder also arrives as a voice message in this voice, and plays if Odie is open."
              : "Needs a voice that's ready: this one isn't available right now."}</div>
          </div>
          <Switch label="Speak reminders" on={!!v.reminders_spoken} disabled={!eng.available && !v.reminders_spoken}
            onChange={(on) => save({ reminders_spoken: on })} />
        </div>
      </Part>
    </>
  );
}
