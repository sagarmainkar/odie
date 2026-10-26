/** Settings' Voice section: which engine to show, or the one line that stands in when there is none (the voice worker
 * off with ODIE_VOICE=off and no OpenAI key): the rest of Settings must render whatever /api/voice answers. */
export type VoiceItem = { id: string; label: string; group?: string; note?: string };
export type Engine = { id: string; label: string; note: string; local: boolean; available: boolean; voices: VoiceItem[] };
export type VoiceInfo = { engine: string; voice: string; engines: Engine[]; models: { tts: string; realtime: string }; reminders_spoken?: boolean; local_voice?: boolean };
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

export const PULL_PHONON_TEXT = "Ollama doesn't have Phonon yet: run `ollama pull phonon` (113 MB), then open Settings again.";
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
 *    Kokoro, its server can't run -> no pill, "The local voice service isn't running: odie restart starts it."
 *    OpenAI without its key       -> no pill, "Add an OpenAI key in Providers to use these voices." */
export function engineLine(eng: Engine): EngineLine {
  if (eng.available) return { pill: eng.local ? "on this computer" : "leaves this computer", text: eng.note };
  if (eng.id === "phonon") return { pill: null, text: PULL_PHONON_TEXT };
  if (eng.local) return { pill: null, text: "The local voice service isn't running: odie restart starts it." };
  return { pill: null, text: "Add an OpenAI key in Providers to use these voices." };
}
