/** Settings' Voice section: which engine to show, or the one line that stands in when there is none (the voice worker
 * off with ODIE_VOICE=off and no OpenAI key): the rest of Settings must render whatever /api/voice answers. */
export type VoiceItem = { id: string; label: string; group?: string; note?: string };
export type Engine = { id: string; label: string; note: string; local: boolean; available: boolean; voices: VoiceItem[] };
export type VoiceInfo = { engine: string; voice: string; engines: Engine[]; models: { tts: string; realtime: string }; reminders_spoken?: boolean; local_voice?: boolean };
export type VoiceSection = { picker: true; engine: Engine } | { picker: false; note: string };

export const NO_VOICE_TEXT = "No voice yet: turn on Odie's own voice at install (ODIE_VOICE) or add an OpenAI key in Settings → Keys.";

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
