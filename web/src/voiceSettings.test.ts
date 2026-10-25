import { describe, expect, it } from "vitest";
import { NO_VOICE_TEXT, voiceSection, type VoiceInfo } from "./voiceSettings";

const local = { id: "kokoro", label: "Odie's voice", note: "", local: true, available: true, voices: [] };
const cloud = { id: "openai", label: "Cloud", note: "", local: false, available: true, voices: [] };
const base: VoiceInfo = { engine: "", voice: "", engines: [], models: { tts: "", realtime: "" } };

describe("the voice section", () => {
  it("shows a plain line, and no picker, when there is no engine at all", () => {
    expect(voiceSection(base)).toEqual({ picker: false, note: NO_VOICE_TEXT });
    expect(NO_VOICE_TEXT).toBe("No voice yet: turn on Odie's own voice at install (ODIE_VOICE) or add an OpenAI key in Settings → Keys.");
  });

  it("shows the picker when an engine exists, picking the chosen one or the first", () => {
    expect(voiceSection({ ...base, engines: [local], engine: "kokoro" })).toEqual({ picker: true, engine: local });
    expect(voiceSection({ ...base, engines: [local, cloud], engine: "openai" })).toEqual({ picker: true, engine: cloud });
    expect(voiceSection({ ...base, engines: [local, cloud], engine: "gone" })).toEqual({ picker: true, engine: local });  // a saved engine that left: the first
  });
});
