import { describe, expect, it } from "vitest";
import { LIBRA_DOWN_TEXT, NO_VOICE_TEXT, PULL_PHONON_TEXT, engineLine, libraToneLabel, showLibra, voiceGroups, voiceRow, voiceSection, type VoiceInfo } from "./voiceSettings";

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

describe("Settings' Voice row", () => {
  const phonon = { id: "phonon", label: "Phonon (Ollama)", note: "", local: true, available: true,
    voices: [{ id: "Zoey", label: "Zoey" }, { id: "Noémie (phonon:fr)", label: "Noémie" }] };

  it("says the chosen voice and its engine, by the names the picker shows", () => {
    expect(voiceRow({ ...base, engines: [phonon], engine: "phonon", voice: "Zoey" })).toEqual({ sub: "Zoey · Phonon (Ollama)", state: "ok" });
    expect(voiceRow({ ...base, engines: [phonon], engine: "phonon", voice: "Noémie (phonon:fr)" }).sub).toBe("Noémie · Phonon (Ollama)");
  });

  it("adds that reminders are spoken when they are", () => {
    expect(voiceRow({ ...base, engines: [phonon], engine: "phonon", voice: "Zoey", reminders_spoken: true }).sub)
      .toBe("Zoey · Phonon (Ollama) · speaks reminders");
  });

  it("falls back to the voice's id when the list doesn't have it", () => {
    expect(voiceRow({ ...base, engines: [phonon], engine: "phonon", voice: "Gone" }).sub).toBe("Gone · Phonon (Ollama)");
  });

  it("warns when the chosen engine can't speak right now", () => {
    expect(voiceRow({ ...base, engines: [{ ...phonon, available: false }], engine: "phonon", voice: "Zoey" }).state).toBe("warn");
  });

  it("says the browser reads replies when there is no engine at all", () => {
    expect(voiceRow(base)).toEqual({ sub: "No voice yet: the browser's own voice reads replies", state: "warn" });
  });
});

describe("Libra in Settings → Voice", () => {
  const libra = { url: "http://127.0.0.1:8794", tone: "", tones: ["warm", "wry"], answering: true };
  const base = { engine: "phonon", voice: "zoey", engines: [], models: { tts: "", realtime: "" } };

  it("shows Libra's part while it's the engine, or while it isn't answering", () => {
    expect(showLibra({ ...base, libra }, "libra")).toBe(true);
    expect(showLibra({ ...base, libra: { ...libra, answering: false } }, "phonon")).toBe(true);
    expect(showLibra({ ...base, libra }, "phonon")).toBe(false);
    expect(showLibra(base, "libra")).toBe(false);
  });

  it("names tones on their buttons", () => {
    expect(libraToneLabel("")).toBe("None");
    expect(libraToneLabel("wry")).toBe("Wry");
  });

  it("says how to start Libra when it can't speak", () => {
    const off = { id: "libra", label: "Libra", note: "", local: true, available: false, voices: [] };
    expect(engineLine(off).text).toBe(LIBRA_DOWN_TEXT);
  });
});
