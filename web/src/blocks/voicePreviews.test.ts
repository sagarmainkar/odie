// A voice option the model wrote without its ▶ preview gets one from the voices of the engine chosen in Settings.
import { describe, expect, it } from "vitest";
import { readBlocks } from "./parse";
import type { ChoiceField, FormBlock } from "./parse/form";
import { voiceListFrom, withVoicePreviews } from "./voicePreviews";

function form(raw: object): FormBlock {
  return readBlocks(JSON.stringify([{ type: "form", ...raw }]))!.blocks[0] as FormBlock;
}

const phonon = { engine: "phonon", voices: [{ id: "Hugh", label: "Hugh" }, { id: "Captain Silas Blackwater", label: "Captain Silas Blackwater" }] };
const kokoro = { engine: "kokoro", voices: [{ id: "af_heart", label: "Heart" }, { id: "bm_george", label: "George" }] };

const cast = form({ id: "cast", fields: [
  { id: "narrator", kind: "select", label: "Narrator", value: "Hugh", options: ["Hugh", "Captain Silas Blackwater", { value: "Nobody", label: "Nobody" }] },
  { id: "keeper", kind: "radio", label: "Keeper", options: [{ value: "Hugh", label: "Hugh", preview: "/api/voice/preview/phonon/Hugh?kept" }, "Horror"] },
  { id: "length", kind: "slider", label: "Length", min: 3, max: 15 },
] });

function options(f: FormBlock, i: number) {
  return (f.fields[i] as ChoiceField).options;
}

describe("voice previews filled in", () => {
  it("gives a voice option of the chosen engine its preview, and leaves everything else as it was", () => {
    const filled = withVoicePreviews(cast, phonon);
    expect(options(filled, 0).map((o) => o.preview)).toEqual([
      "/api/voice/preview/phonon/Hugh", "/api/voice/preview/phonon/Captain%20Silas%20Blackwater", undefined]);
    expect(options(filled, 1)[0].preview).toBe("/api/voice/preview/phonon/Hugh?kept");  // its own preview stays
    expect(options(filled, 1)[1].preview).toBeUndefined();  // "Horror" is no voice
    expect(filled.fields[2]).toEqual(cast.fields[2]);
  });

  it("knows a voice by its label too, and previews it by its id", () => {
    const f = form({ fields: [{ id: "who", kind: "select", options: ["heart", "Bella"] }] });
    expect(options(withVoicePreviews(f, kokoro), 0).map((o) => o.preview)).toEqual(["/api/voice/preview/kokoro/af_heart", undefined]);
  });

  it("changes nothing without a voice list", () => {
    expect(withVoicePreviews(cast, null)).toBe(cast);
  });

  it("reads the chosen engine's voices from what /api/voice answers", () => {
    const answer = { engine: "phonon", engines: [{ id: "kokoro", voices: [{ id: "af_heart", label: "Heart" }] }, { id: "phonon", voices: phonon.voices }] };
    expect(voiceListFrom(answer)).toEqual(phonon);
    expect(voiceListFrom({ engine: "gone", engines: [] })).toBeNull();
    expect(voiceListFrom("nonsense")).toBeNull();
  });
});
