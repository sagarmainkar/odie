import { describe, expect, it } from "vitest";
import { quietAfterIdle } from "./dictation";
import { applyEvent, composerWith, emptyText, levelOf, pickMode, smoothLevel, textOf } from "./dictation";

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
    const quiet = levelOf(new Uint8Array([131, 125, 131, 125]));  // a soft voice on a phone, noise suppression on
    expect(quiet).toBeGreaterThan(0.2);  // still shows: a voice moves the wave
    expect(quiet).toBeLessThan(0.5);
    const normal = levelOf(new Uint8Array([141, 115, 141, 115]));
    expect(normal).toBeGreaterThan(0.5);
    expect(normal).toBeLessThan(1);
  });

  it("smooths the level: it jumps up with the voice and falls back slowly, so the wave doesn't flicker", () => {
    expect(smoothLevel(0, 1)).toBeGreaterThan(0.5);   // a word starts: most of the way up at once
    expect(smoothLevel(1, 0)).toBeGreaterThan(0.8);   // a pause: only a little way down per frame
    expect(smoothLevel(0.4, 0.4)).toBeCloseTo(0.4);
  });

  // The composer as Chat keeps it: the mic writes through composerWith, the user sends, clears or types.
  function composer(start: string) {
    let box = start;
    let written = start;
    const base = start.trim();
    return {
      hear: (words: string) => {
        const next = composerWith({ composer: box, written, base, words });
        if (next !== null) { box = next; written = next; }
      },
      user: (text: string) => { box = text; },
      get box() { return box; },
    };
  }

  it("writes the dictated words after what was already typed", () => {
    const c = composer("Plan");
    c.hear("a trip");
    c.hear("a trip to Goa");
    expect(c.box).toBe("Plan a trip to Goa");
  });

  it("drops a phrase that arrives after the message was sent, so the next turn starts empty", () => {
    const c = composer("");
    c.hear("Plan a weekend in Mahabaleshwar");
    c.user("");  // sent: the composer clears
    c.hear("Plan a weekend in Mahabaleshwar for four");  // the last phrase, arriving late
    expect(c.box).toBe("");
  });

  it("keeps the composer cleared when the user clears it mid-dictation", () => {
    const c = composer("");
    c.hear("Track my December");
    c.user("");  // cleared while the mic still listens
    c.hear("Track my December puts");
    expect(c.box).toBe("");
  });

  it("leaves what the user typed alone once they take over", () => {
    const c = composer("");
    c.hear("Remind me tomorrow");
    c.user("Remind me tomorrow at 9");
    c.hear("Remind me tomorrow to call");
    expect(c.box).toBe("Remind me tomorrow at 9");
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
