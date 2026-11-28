/** Settings' Voice section: which engine to show, or the one line that stands in when there is none (the voice worker
 * off with ODIE_VOICE=off and no OpenAI key): the rest of Settings must render whatever /api/voice answers. */
export type VoiceItem = { id: string; label: string; group?: string; note?: string; gender?: string | null; kept?: boolean };
export type Engine = { id: string; label: string; note: string; local: boolean; available: boolean; voices: VoiceItem[] };
export type LibraInfo = { url: string; tone: string; tones: string[]; answering: boolean; speed?: string; speeds?: string[] };
export type VoiceInfo = { engine: string; voice: string; engines: Engine[]; models: { tts: string; realtime: string }; reminders_spoken?: boolean; local_voice?: boolean; libra?: LibraInfo };
export type VoiceSection = { picker: true; engine: Engine } | { picker: false; note: string };

export const NO_VOICE_TEXT = "No voice yet: turn on Odie's own voice at install (ODIE_VOICE) or add an OpenAI key in Settings → Providers.";

/** What the Voice section shows: with any engine, the picker on the chosen engine (or the first when the chosen one
 *  is gone); with no engine at all, one plain line (NO_VOICE_TEXT) and no picker, so nothing reads a field of an
 *  engine that isn't there.
 *    engines [kokoro], engine "kokoro"        -> picker on kokoro
 *    engines [kokoro, openai], engine "gone"  -> picker on kokoro (the first)
 *    engines []                               -> no picker, NO_VOICE_TEXT */
export function voiceSection(v: VoiceInfo): VoiceSection {
  const chosen = v.engines.find((e) => e.id === v.engine) ?? v.engines[0];
  if (!chosen) return { picker: false, note: NO_VOICE_TEXT };
  return { picker: true, engine: chosen };
}

export type VoiceRow = { sub: string; state: "ok" | "warn" };

/** Settings' Voice row, which opens the Voice screen: the chosen voice and its engine by the names the picker shows,
 *  and whether that engine can speak right now.
 *    Phonon, voice "Zoey", available           -> "Zoey · Phonon (Ollama)", ok
 *    the same with reminders spoken            -> "Zoey · Phonon (Ollama) · speaks reminders", ok
 *    a voice the list no longer has ("Gone")   -> "Gone · Phonon (Ollama)", ok
 *    Phonon not pulled in Ollama               -> "Zoey · Phonon (Ollama)", warn
 *    no engine at all                          -> "No voice yet: the browser's own voice reads replies", warn */
export function voiceRow(v: VoiceInfo): VoiceRow {
  const shown = voiceSection(v);
  if (!shown.picker) return { sub: "No voice yet: the browser's own voice reads replies", state: "warn" };
  const engine = shown.engine;
  const listed = engine.voices.find((x) => x.id === v.voice);
  const voiceName = listed ? listed.label : v.voice;
  const parts = [voiceName, engine.label];
  if (v.reminders_spoken) parts.push("speaks reminders");
  const state = engine.available ? "ok" : "warn";
  return { sub: parts.join(" · "), state };
}

export const PULL_PHONON_TEXT = "Ollama doesn't have Phonon yet: run `ollama pull phonon` (113 MB), then open Settings again.";
export const LIBRA_DOWN_TEXT = "The Libra voice server isn't answering: start it with ./libra start, or fix its address below.";

/** How a Libra tone is named on its button: "" -> "None"; "wry" -> "Wry"; "documentary" -> "Documentary". */
export function libraToneLabel(tone: string): string {
  if (!tone) return "None";
  return tone.charAt(0).toUpperCase() + tone.slice(1);
}

/** Whether Settings → Voice shows Libra's part (tone and server address): while Libra is the engine, and while it
 *  isn't answering, so its address can be fixed before it can be chosen.
 *    Libra chosen and answering            -> true
 *    Phonon chosen, Libra not answering    -> true
 *    Phonon chosen, Libra answering        -> false
 *    an older Odie that sends no libra     -> false */
export function showLibra(v: VoiceInfo, engineId: string): boolean {
  if (!v.libra) return false;
  return engineId === "libra" || !v.libra.answering;
}

export type VoiceGroup = { key: string; title: string; voices: VoiceItem[] };
export type EngineLine = { pill: "on this computer" | "leaves this computer" | null; text: string };

const GENDER_TITLES: [string, string][] = [["female", "Female voices"], ["male", "Male voices"], ["neutral", "Neutral"]];

/** The picker's groups for one engine, each with its heading. Kokoro's and OpenAI's female, male and neutral groups
 *  keep their headings and that order (a voice with no group counts as neutral, as before); any other group (Phonon's
 *  "American · Female", "Characters") is drawn under its own name, in the order the server lists the voices; a group
 *  of "" gets no heading.
 *    Kokoro [michael (male), heart (female)]   -> Female voices [heart], Male voices [michael]
 *    Phonon [Zoey (American · Female), Easton (American · Male), Ada (American · Female)]
 *                                               -> American · Female [Zoey, Ada], American · Male [Easton]
 *    Phonon [zoey (""), easton ("")]            -> one group with no heading [zoey, easton] */
export function voiceGroups(eng: Engine): VoiceGroup[] {
  const byGender = new Map<string, VoiceItem[]>();
  const others = new Map<string, VoiceItem[]>();
  for (const voice of eng.voices) {
    const group = voice.group ?? "neutral";
    const isGender = GENDER_TITLES.some(([key]) => key === group);
    const into = isGender ? byGender : others;
    into.set(group, [...(into.get(group) ?? []), voice]);
  }
  const genderGroups = GENDER_TITLES.filter(([key]) => byGender.has(key))
    .map(([key, title]) => ({ key, title, voices: byGender.get(key) ?? [] }));
  const otherGroups = [...others.entries()].map(([key, voices]) => ({ key, title: key, voices }));
  return [...genderGroups, ...otherGroups];
}

/** The line under the engine buttons: whether its voices stay on this computer, and the engine's note; when it can't
 *  speak, what to do instead.
 *    Phonon, Ollama has it        -> pill "on this computer", its note
 *    Phonon, Ollama doesn't       -> no pill, PULL_PHONON_TEXT
 *    Libra, its server is off     -> no pill, LIBRA_DOWN_TEXT
 *    Kokoro, its server can't run -> no pill, "The local voice service isn't running: odie restart starts it."
 *    OpenAI without its key       -> no pill, "Add an OpenAI key in Providers to use these voices." */
export function engineLine(eng: Engine): EngineLine {
  if (eng.available) return { pill: eng.local ? "on this computer" : "leaves this computer", text: eng.note };
  if (eng.id === "phonon") return { pill: null, text: PULL_PHONON_TEXT };
  if (eng.id === "libra") return { pill: null, text: LIBRA_DOWN_TEXT };
  if (eng.local) return { pill: null, text: "The local voice service isn't running: odie restart starts it." };
  return { pill: null, text: "Add an OpenAI key in Providers to use these voices." };
}

/** A voice's preview address. Phonon's voice ids are names as Ollama spells them, with spaces, accents and brackets
 *  ("Noémie (phonon:fr)"), so the id is encoded: "Captain Silas Blackwater" -> ".../Captain%20Silas%20Blackwater". */
/** A voice's preview: for Libra, in a tone and at a speed. ("libra", "sofia", "wry", "quick") ->
 *  "/api/voice/preview/libra/sofia?tone=wry&speed=quick"; ("phonon", "Harper") -> "/api/voice/preview/phonon/Harper". */
export function previewUrl(engine: string, voiceId: string, tone?: string, speed?: string): string {
  const url = `/api/voice/preview/${encodeURIComponent(engine)}/${encodeURIComponent(voiceId)}`;
  const how = new URLSearchParams();
  if (tone) how.set("tone", tone);
  if (speed) how.set("speed", speed);
  const query = how.toString();
  return query ? `${url}?${query}` : url;
}

/** How Libra's speeds are named on their buttons: "brisk" -> "A bit quicker"; an unknown one -> itself. */
export function libraSpeedLabel(speed: string): string {
  const names: Record<string, string> = { normal: "As it reads", brisk: "A bit quicker", quick: "Quicker" };
  return names[speed] ?? speed;
}

// "Another voice": a Phonon voice name the user types, which the server tries against the Phonon models Ollama has.
export const NAME_LIMIT = 80;
export type AnotherState =
  | { kind: "idle" } | { kind: "trying" } | { kind: "kept"; voice: string } | { kind: "chosen"; voice: string } | { kind: "refused"; message: string };
export type PhononAnswer = { engine: string; voice: string; voices: VoiceItem[] };

/** Whether "Try it" may ask the server: a name with something in it, at most NAME_LIMIT characters, and no try
 *  already under way. "Noémie" -> true; "   " -> false; 81 characters -> false; "Noémie" while trying -> false. */
export function canTry(name: string, state: AnotherState): boolean {
  const typed = name.trim();
  if (!typed || typed.length > NAME_LIMIT) return false;
  return state.kind !== "trying";
}

/** The line under the box: nothing before a try, "Trying it…" during one, where a kept voice went, or the server's
 *  own words for a refusal (they say which model to pull). */
export function anotherLine(state: AnotherState): string {
  if (state.kind === "trying") return "Trying it…";
  if (state.kind === "kept") return `Kept ${state.voice} under Your voices.`;
  if (state.kind === "chosen") return `${state.voice} is already in the list: chosen.`;
  if (state.kind === "refused") return state.message;
  return "";
}

/** How a try that worked went: a voice Ollama already lists was just chosen ("chosen", by its listed name), a new one
 *  was kept under Your voices ("kept", as typed). Typed "ZOEY", Zoey listed -> chosen "Zoey"; typed "Noémie", answer's
 *  voice is the kept "Noémie (phonon:fr)" -> kept "Noémie". */
export function triedState(answer: PhononAnswer, typed: string): AnotherState {
  const voice = answer.voices.find((x) => x.id === answer.voice);
  if (voice && !voice.kept) return { kind: "chosen", voice: voice.label };
  return { kind: "kept", voice: typed };
}

/** Asks the server to try a typed name: its answer (the chosen voice and Phonon's list) when a model speaks it, else
 *  the server's reason, or a plain line when the server couldn't be reached. */
export async function tryAnotherVoice(name: string): Promise<{ ok: true; answer: PhononAnswer } | { ok: false; message: string }> {
  try {
    const r = await fetch("/api/voice/phonon/check", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }) });
    const body = await r.json();
    if (r.ok) return { ok: true, answer: body as PhononAnswer };
    return { ok: false, message: String(body?.detail || "That voice couldn't be tried.") };
  } catch {
    return { ok: false, message: "Odie didn't answer: try again." };
  }
}

/** The picker after the server answered about Phonon's voices (a kept or removed voice): the chosen engine and voice,
 *  and Phonon's new list; the other engines stay exactly as they were. */
export function withPhononVoices(v: VoiceInfo, answer: PhononAnswer): VoiceInfo {
  const engines = v.engines.map((e) => (e.id === "phonon" ? { ...e, voices: answer.voices } : e));
  return { ...v, engine: answer.engine, voice: answer.voice, engines };
}
