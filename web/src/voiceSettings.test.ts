import { describe, expect, it } from "vitest";
import { NO_VOICE_TEXT, PULL_PHONON_TEXT, engineLine, voiceGroups, voiceSection, type VoiceInfo } from "./voiceSettings";

const local = { id: "kokoro", label: "Odie's voice", note: "", local: true, available: true, voices: [] };
const cloud = { id: "openai", label: "Cloud", note: "", local: false, available: true, voices: [] };
const base: VoiceInfo = { engine: "", voice: "", engines: [], models: { tts: "", realtime: "" } };

describe("the voice section", () => {
  it("shows a plain line, and no picker, when there is no engine at all", () => {
    expect(voiceSection(base)).toEqual({ picker: false, note: NO_VOICE_TEXT });
    expect(NO_VOICE_TEXT).toBe("No voice yet: turn on Odie's own voice at install (ODIE_VOICE) or add an OpenAI key in Settings → Providers.");
  });

  it("shows the picker when an engine exists, picking the chosen one or the first", () => {
    expect(voiceSection({ ...base, engines: [local], engine: "kokoro" })).toEqual({ picker: true, engine: local });
    expect(voiceSection({ ...base, engines: [local, cloud], engine: "openai" })).toEqual({ picker: true, engine: cloud });
    expect(voiceSection({ ...base, engines: [local, cloud], engine: "gone" })).toEqual({ picker: true, engine: local });  // a saved engine that left: the first
  });
});

describe("the voice picker's groups and engine line", () => {
  const v = (id: string, group?: string) => ({ id, label: id, group });

  it("keeps Kokoro's and OpenAI's female, male and neutral headings, in that order", () => {
    const kokoro = { ...local, voices: [v("am_michael", "male"), v("af_heart", "female"), v("alloy")] };
    expect(voiceGroups(kokoro).map((g) => [g.title, g.voices.map((x) => x.id)])).toEqual([
      ["Female voices", ["af_heart"]], ["Male voices", ["am_michael"]], ["Neutral", ["alloy"]]]);
  });

  it("draws any other group under its own heading, in the order the server lists them", () => {
    const phonon = { ...local, id: "phonon", voices: [v("Zoey", "American · Female"), v("Easton", "American · Male"), v("Ada", "American · Female")] };
    expect(voiceGroups(phonon).map((g) => [g.title, g.voices.map((x) => x.id)])).toEqual([
      ["American · Female", ["Zoey", "Ada"]], ["American · Male", ["Easton"]]]);
  });

  it("shows voices with no group yet under no heading at all", () => {
    const phonon = { ...local, id: "phonon", voices: [v("zoey", ""), v("easton", "")] };
    expect(voiceGroups(phonon)).toEqual([{ key: "", title: "", voices: [v("zoey", ""), v("easton", "")] }]);
  });

  it("says what to run when Ollama doesn't have Phonon", () => {
    const phonon = { id: "phonon", label: "Phonon (Ollama)", note: "Quick.", local: true, available: false, voices: [] };
    expect(engineLine(phonon)).toEqual({ pill: null, text: PULL_PHONON_TEXT });
    expect(PULL_PHONON_TEXT).toContain("run `ollama pull phonon`");
    expect(engineLine({ ...phonon, available: true })).toEqual({ pill: "on this computer", text: "Quick." });
    expect(engineLine({ ...local, available: false }).text).toBe("The local voice service isn't running: odie restart starts it.");
    expect(engineLine({ ...cloud, note: "Cloud voices." })).toEqual({ pill: "leaves this computer", text: "Cloud voices." });
  });
});
