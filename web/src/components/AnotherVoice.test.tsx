// @vitest-environment jsdom
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AnotherVoiceView } from "./AnotherVoice";
import { anotherLine, canTry, previewUrl, triedState, tryAnotherVoice, withPhononVoices, type VoiceInfo } from "../voiceSettings";

const refusal = 'No Phonon model here has a voice called "Noémie". French, German, Spanish and Portuguese voices need another Phonon model, for example: ollama pull phonon:fr';

describe("Another voice", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("builds preview addresses that survive spaces, accents and brackets", () => {
    expect(previewUrl("phonon", "Captain Silas Blackwater")).toBe("/api/voice/preview/phonon/Captain%20Silas%20Blackwater");
    expect(previewUrl("phonon", "Noémie (phonon:fr)")).toBe("/api/voice/preview/phonon/No%C3%A9mie%20(phonon%3Afr)");
    expect(previewUrl("kokoro", "af_heart")).toBe("/api/voice/preview/kokoro/af_heart");
  });

  it("asks only about a name worth asking, one at a time", () => {
    expect(canTry("Noémie", { kind: "idle" })).toBe(true);
    expect(canTry("   ", { kind: "idle" })).toBe(false);
    expect(canTry("x".repeat(81), { kind: "idle" })).toBe(false);
    expect(canTry("Noémie", { kind: "trying" })).toBe(false);
  });

  it("says each state in words", () => {
    expect(anotherLine({ kind: "idle" })).toBe("");
    expect(anotherLine({ kind: "trying" })).toBe("Trying it…");
    expect(anotherLine({ kind: "kept", voice: "Noémie" })).toBe("Kept Noémie under Your voices.");
    expect(anotherLine({ kind: "refused", message: refusal })).toBe(refusal);
  });

  it("draws the box, the button and the state line", () => {
    const trying = renderToStaticMarkup(<AnotherVoiceView name="Noémie" state={{ kind: "trying" }} onName={() => {}} onTry={() => {}} />);
    expect(trying).toContain('placeholder="Another voice name"');
    expect(trying).toMatch(/<button[^>]*disabled=""[^>]*>Try it<\/button>/);
    expect(trying).toContain("Trying it…");
    const refused = renderToStaticMarkup(<AnotherVoiceView name="Noémie" state={{ kind: "refused", message: refusal }} onName={() => {}} onTry={() => {}} />);
    expect(refused).toContain("ollama pull phonon:fr");
    expect(refused).toMatch(/<button[^>]*>Try it<\/button>/);
    expect(refused).not.toMatch(/<button[^>]*disabled=""[^>]*>Try it/);
    const kept = renderToStaticMarkup(<AnotherVoiceView name="" state={{ kind: "kept", voice: "Noémie" }} onName={() => {}} onTry={() => {}} />);
    expect(kept).toContain("Kept Noémie under Your voices.");
  });

  it("reads the server's answer: kept, or refused with its words", async () => {
    const answer = { engine: "phonon", voice: "Noémie (phonon:fr)", voices: [{ id: "Noémie (phonon:fr)", label: "Noémie", group: "Your voices", kept: true }] };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(answer), { status: 200 })));
    expect(await tryAnotherVoice("Noémie")).toEqual({ ok: true, answer });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: refusal }), { status: 422 })));
    expect(await tryAnotherVoice("Noémie")).toEqual({ ok: false, message: refusal });
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("offline"); }));
    expect(await tryAnotherVoice("Noémie")).toEqual({ ok: false, message: "Odie didn't answer: try again." });
  });

  it("puts the answer into the picker: the chosen voice and Phonon's new list", () => {
    const zoey = { id: "zoey", label: "Zoey", group: "American · Female" };
    const before: VoiceInfo = { engine: "kokoro", voice: "af_heart", models: { tts: "", realtime: "" }, engines: [
      { id: "kokoro", label: "Kokoro", note: "", local: true, available: true, voices: [] },
      { id: "phonon", label: "Phonon (Ollama)", note: "", local: true, available: true, voices: [zoey] }] };
    const mine = { id: "Noémie (phonon:fr)", label: "Noémie", group: "Your voices", kept: true };
    const after = withPhononVoices(before, { engine: "phonon", voice: mine.id, voices: [zoey, mine] });
    expect(after.engine).toBe("phonon");
    expect(after.voice).toBe("Noémie (phonon:fr)");
    expect(after.engines[1].voices).toEqual([zoey, mine]);
    expect(after.engines[0]).toBe(before.engines[0]);  // Kokoro untouched
  });

  it("says a listed voice was chosen, and a new one kept", () => {
    const zoey = { id: "zoey", label: "Zoey", group: "American · Female" };
    const mine = { id: "Noémie (phonon:fr)", label: "Noémie", group: "Your voices", kept: true };
    const listed = triedState({ engine: "phonon", voice: "zoey", voices: [zoey, mine] }, "ZOEY");
    expect(listed).toEqual({ kind: "chosen", voice: "Zoey" });
    expect(anotherLine(listed)).toBe("Zoey is already in the list: chosen.");
    expect(triedState({ engine: "phonon", voice: "Noémie (phonon:fr)", voices: [zoey, mine] }, "Noémie")).toEqual({ kind: "kept", voice: "Noémie" });
  });
});
