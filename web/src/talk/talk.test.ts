import { describe, expect, it } from "vitest";
import { canInterrupt, faceFor } from "./phase";
import { Gatherer } from "./gather";
import { closedBecause, levelOf, listenUrl } from "./hearing";
import { Resampler, toInt16 } from "./pcm";
import { TalkSentences, sentencesIn, speechOf, toneOf } from "./sentences";
import { TalkSpeaker } from "./speaker";

describe("16 kHz for Odie's ears", () => {
  it("turns floats into clipped 16-bit samples", () => {
    expect(toInt16(0.5)).toBe(16384);
    expect(toInt16(-1)).toBe(-32767);
    expect(toInt16(1.7)).toBe(32767);
  });

  it("keeps a third of the samples at 48 kHz, joining pieces without losing any", () => {
    const resampler = new Resampler(48000);
    let total = 0;
    for (let piece = 0; piece < 10; piece++) total += resampler.push(new Float32Array(2048)).length;
    expect(Math.abs(total - Math.round(20480 / 3))).toBeLessThanOrEqual(1);
  });

  it("works at 44.1 kHz too", () => {
    const resampler = new Resampler(44100);
    let total = 0;
    for (let piece = 0; piece < 20; piece++) total += resampler.push(new Float32Array(2048)).length;
    expect(Math.abs(total - Math.round(40960 * 16000 / 44100))).toBeLessThanOrEqual(1);
  });

  it("follows the wave it is given", () => {
    const resampler = new Resampler(48000);
    const ramp = Float32Array.from({ length: 300 }, (_, i) => i / 300);
    const out = resampler.push(ramp);
    expect(out[0]).toBe(0);
    expect(out[50]).toBe(toInt16(150 / 300));
  });
});

describe("what Talk says of a reply", () => {
  it("finds the tone", () => {
    expect(toneOf("<tone:wry>You paid twice?")).toBe("wry");
    expect(toneOf("Plain.")).toBeNull();
  });

  it("says only the prose, with the sound tags but not the tone", () => {
    const reply = "<tone:calm>**Paid.** See:\n```odie-blocks\n[{\"type\":\"divider\"}]\n```\nDone. <chuckle>";
    expect(sentencesIn(speechOf(reply)).map((s) => s.text)).toEqual(["Paid.", "See:", "Done. <chuckle>"]);
  });

  it("never reads a table or an unfinished fence", () => {
    expect(speechOf("Here:\n| a | b |\n|---|---|\n| 1 | 2 |\nThat's all.")).toBe("Here:\nThat's all.");
    expect(speechOf("Look.\n```odie-blocks\n[{\"type\"")).toBe("Look.\n");
  });

  it("hands each finished sentence over once, as the reply streams", () => {
    const stream = new TalkSentences();
    expect(stream.feed("<tone:wry>You paid the bill twice? <la")).toEqual(["You paid the bill twice?"]);
    expect(stream.feed("<tone:wry>You paid the bill twice? <laugh> No harm")).toEqual([]);
    expect(stream.finish("<tone:wry>You paid the bill twice? <laugh> No harm done.")).toEqual(["<laugh> No harm done."]);
    expect(stream.finish("<tone:wry>You paid the bill twice? <laugh> No harm done.")).toEqual([]);
  });

  it("waits for what follows a full stop at the very end of a streaming reply", () => {
    const stream = new TalkSentences();
    expect(stream.feed("Your bill was ₹4,240.")).toEqual([]);
    expect(stream.feed("Your bill was ₹4,240.50 this month. Paid")).toEqual(["Your bill was ₹4,240.50 this month."]);
  });

  it("keeps amounts and decimals in one sentence", () => {
    expect(sentencesIn("The bill was ₹4,240.50 this month. Paid.").map((s) => s.text))
      .toEqual(["The bill was ₹4,240.50 this month.", "Paid."]);
  });
});

describe("the voice queue", () => {
  function fakeContext() {
    const started: number[] = [];
    const sources: { onended: (() => void) | null; stopped: boolean }[] = [];
    const context = {
      currentTime: 0,
      destination: {},
      decodeAudioData: async (bytes: ArrayBuffer) => ({ duration: bytes.byteLength / 10 }),
      createBufferSource: () => {
        const source = { buffer: null, onended: null as (() => void) | null, stopped: false,
          connect: () => {}, start: (at: number) => { started.push(at); }, stop: () => { source.stopped = true; } };
        sources.push(source);
        return source;
      },
    };
    return { context: context as unknown as AudioContext, started, sources };
  }

  it("asks for each sentence with the reply's tone and plays them back to back", async () => {
    const { context, started, sources } = fakeContext();
    const asked: [string, string | null][] = [];
    const speaker = new TalkSpeaker(context, async (text, tone) => { asked.push([text, tone]); return new ArrayBuffer(10); });
    const heard: boolean[] = [];
    speaker.onSpeaking = (on) => heard.push(on);
    speaker.say("One.", "wry");
    speaker.say("Two.", "wry");
    await new Promise((resolve) => setTimeout(resolve, 0));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(asked).toEqual([["One.", "wry"], ["Two.", "wry"]]);
    expect(started.length).toBe(2);
    expect(started[1]).toBeCloseTo(started[0] + 1);  // the second starts as the first ends
    const quiet = speaker.whenQuiet();
    for (const source of sources) source.onended?.();
    await quiet;
    expect(heard).toEqual([true, false]);
  });

  it("stops at once and forgets what was asked before", async () => {
    const { context, started, sources } = fakeContext();
    let release: (bytes: ArrayBuffer) => void = () => {};
    const speaker = new TalkSpeaker(context, (_text, _tone, signal) => new Promise((resolve, reject) => {
      release = resolve;
      signal.addEventListener("abort", () => reject(new Error("aborted")));
    }));
    speaker.say("One.", null);
    speaker.stop();
    release(new ArrayBuffer(10));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(started).toEqual([]);
    expect(sources.length).toBe(0);
    expect(speaker.quiet).toBe(true);
  });
});

describe("the Talk screen's rules", () => {
  it("shows the right face and only offers Interrupt while Odie answers", () => {
    expect(faceFor("you")).toBe("listening");
    expect(faceFor("thinking")).toBe("thinking");
    expect(faceFor("connecting")).toBe("idle");
    expect(canInterrupt("speaking")).toBe(true);
    expect(canInterrupt("thinking")).toBe(true);
    expect(canInterrupt("listening")).toBe(false);
  });

  it("listens on the app's own host and says why it stopped", () => {
    expect(listenUrl({ protocol: "https:", host: "odie.example.ts.net" })).toBe("wss://odie.example.ts.net/api/talk/listen");
    expect(listenUrl({ protocol: "http:", host: "studio.local:8000" })).toBe("ws://studio.local:8000/api/talk/listen");
    expect(closedBecause(4503, "Odie's voice server isn't set up.")).toBe("Odie's voice server isn't set up.");
    expect(closedBecause(1006, "")).toBe("Lost the connection to Odie.");
    expect(levelOf(new Float32Array(4))).toBe(0);
  });
});

describe("when you have finished speaking", () => {
  function fakeTimers() {
    const waiting = new Map<number, () => void>();
    let next = 1;
    return {
      timers: { set: (run: () => void) => { waiting.set(next, run); return next++; }, clear: (id: number) => { waiting.delete(id); } },
      pass: () => { const runs = [...waiting.values()]; waiting.clear(); runs.forEach((run) => run()); },
      pending: () => waiting.size,
    };
  }

  it("joins pieces split by a breath into one turn", () => {
    const sent: string[] = [];
    const clock = fakeTimers();
    const gather = new Gatherer((words) => sent.push(words), clock.timers);
    gather.finalWords("There was no moon.");
    gather.speechStarted();  // you went on before the wait passed
    expect(clock.pending()).toBe(0);
    gather.finalWords("it was going to be a long night.");
    expect(gather.words).toBe("There was no moon. it was going to be a long night.");
    clock.pass();
    expect(sent).toEqual(["There was no moon. it was going to be a long night."]);
  });

  it("sends nothing for a cough with no words, and starts afresh after a reset", () => {
    const sent: string[] = [];
    const clock = fakeTimers();
    const gather = new Gatherer((words) => sent.push(words), clock.timers);
    gather.finalWords("  ");
    expect(clock.pending()).toBe(0);
    gather.finalWords("Hello.");
    gather.reset();
    clock.pass();
    expect(sent).toEqual([]);
    expect(gather.words).toBe("");
  });
});
