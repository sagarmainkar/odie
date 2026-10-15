/// <reference types="node" />
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { HOST_TEXT, HOST_TONES, clock, filled, hostInitial, speakingAt, turnAt, withMedia, type Media } from "./media";

const memo: Media = { id: "0123456789abcdef", kind: "memo", title: "Morning", mime: "audio/wav", size: 10, created: 1, duration: 3.5, peaks: [0.2, 1, 0.5, 0.1] };
const pod: Media = {
  id: "fedcba9876543210", kind: "podcast", title: "Our session", mime: "audio/wav", size: 10, created: 1, duration: 9,
  hosts: [{ name: "Asha", group: "female" }, { name: "Rohan", group: "male" }],
  transcript: [{ host: "Asha", text: "Hi", start: 0 }, { host: "Rohan", text: "Hello", start: 2.5 }, { host: "Asha", text: "So", start: 6 }],
};

describe("media", () => {
  it("shows times as m:ss", () => {
    expect(clock(0)).toBe("0:00");
    expect(clock(65.7)).toBe("1:05");
    expect(clock(600)).toBe("10:00");
    expect(clock(-3)).toBe("0:00");
    expect(clock(Number.NaN)).toBe("0:00");
  });

  it("fills the waveform up to where it's played", () => {
    expect(filled([1, 1, 1, 1], 0)).toEqual([false, false, false, false]);
    expect(filled([1, 1, 1, 1], 0.5)).toEqual([true, true, false, false]);
    expect(filled([1, 1, 1, 1], 1)).toEqual([true, true, true, true]);
  });

  it("knows who is speaking when", () => {
    expect(turnAt(pod, 0)).toBe(0);
    expect(turnAt(pod, 3)).toBe(1);
    expect(turnAt(pod, 8)).toBe(2);
    expect(speakingAt(pod, 3)).toBe(1);
    expect(speakingAt(pod, 7)).toBe(0);
    expect(speakingAt(memo, 1)).toBe(-1);
  });

  it("puts what a tool made on the reply being written, once", () => {
    const msgs: { role: string; text: string; media?: Media[] }[] = [{ role: "user", text: "hi" }, { role: "odie", text: "" }];
    const once = withMedia(msgs, memo);
    expect(once[1]).toEqual({ role: "odie", text: "", media: [memo] });
    expect(withMedia(once, memo)).toBe(once);
    expect(withMedia(once, pod)[1].media).toEqual([memo, pod]);
    expect(msgs[1]).toEqual({ role: "odie", text: "" });  // the original is untouched
  });
});

describe("media fixes", () => {
  it("puts media on the reply being written even when a reminder came after it", () => {
    const msgs: { id: number; role: string; text: string; media?: Media[] }[] = [
      { id: 1, role: "user", text: "podcast please" }, { id: 2, role: "odie", text: "" }, { id: 3, role: "odie", text: "Reminder: call mum" }];
    const out = withMedia(msgs, pod, (x) => x.id === 2);
    expect(out[1].media).toEqual([pod]);
    expect(out[2].media).toBeUndefined();
  });

  it("gives each host a solid colour (gradients are dropped from rings and text)", () => {
    const css = readFileSync(new URL("./styles.css", import.meta.url), "utf8");
    expect(HOST_TONES).toEqual(["var(--t-brand)", "var(--t-host-b)"]);
    expect(HOST_TEXT).toEqual(["var(--t-brand-text)", "var(--t-host-b-text)"]);
    for (const v of ["--t-host-b", "--t-host-b-text"]) expect(css).toMatch(new RegExp(`${v}: #[0-9A-Fa-f]{6};`));
  });

  it("calls speak's step Recording", async () => {
    const { toolLabel } = await import("./components/Steps");
    expect(toolLabel({ name: "speak", done: false })).toBe("Recording");
    expect(toolLabel({ name: "speak", done: true })).toBe("Recorded");
  });
});

describe("podcast host avatars", () => {
  it("give the skill's neutral labels different letters", () => {
    expect([hostInitial("Host A"), hostInitial("Host B")]).toEqual(["A", "B"]);
    expect(hostInitial("asha")).toBe("A");
  });
});
