import { describe, expect, it } from "vitest";
import { quietAfterIdle } from "./dictation";
import { applyEvent, emptyText, levelOf, pickMode, textOf } from "./dictation";

describe("dictation", () => {
  it("picks live text with an OpenAI key, the phone's own without one, and says so when neither works", () => {
    expect(pickMode({ dictation: true, phoneSpeech: true })).toBe("live");
    expect(pickMode({ dictation: true, phoneSpeech: false })).toBe("live");
    expect(pickMode({ dictation: false, phoneSpeech: true })).toBe("phone");
    expect(pickMode({ dictation: false, phoneSpeech: false })).toBe("none");  // never a silent mic
  });

  it("builds the text as the words stream in, phrase by phrase", () => {
    let s = emptyText();
    s = applyEvent(s, { type: "conversation.item.input_audio_transcription.delta", item_id: "a", delta: "Track my " });
    s = applyEvent(s, { type: "conversation.item.input_audio_transcription.delta", item_id: "a", delta: "December puts" });
    expect(textOf(s)).toBe("Track my December puts");
    s = applyEvent(s, { type: "conversation.item.input_audio_transcription.completed", item_id: "a", transcript: "Track my December puts." });
    s = applyEvent(s, { type: "conversation.item.input_audio_transcription.delta", item_id: "b", delta: "every five" });
    expect(textOf(s)).toBe("Track my December puts. every five");  // the finished phrase is the model's final wording
    s = applyEvent(s, { type: "session.updated" });  // anything else changes nothing
    expect(textOf(s)).toBe("Track my December puts. every five");
  });

  it("measures the voice level from the microphone samples", () => {
    expect(levelOf(new Uint8Array([128, 128, 128, 128]))).toBe(0);  // silence sits at the middle
    expect(levelOf(new Uint8Array([255, 0, 255, 0]))).toBeGreaterThan(0.9);
    const quiet = levelOf(new Uint8Array([138, 118, 138, 118]));
    expect(quiet).toBeGreaterThan(0.05);
    expect(quiet).toBeLessThan(0.5);
  });
  it("drops text that arrives after the mic went idle, so a late phrase can't undo the user's edits", () => {
    const got: string[] = [];
    const states: string[] = [];
    const h = quietAfterIdle({ onText: (t) => got.push(t), onState: (s) => states.push(s), onLevel: () => {}, onError: () => {} });
    h.onState("recording");
    h.onText("Long weekend");
    h.onText("Long weekend in Yosemite");
    h.onState("idle");
    h.onText("Long weekend in Yosemite, the two of us");  // late, after the user may have started typing
    expect(got).toEqual(["Long weekend", "Long weekend in Yosemite"]);
    expect(states).toEqual(["recording", "idle"]);
  });
});
