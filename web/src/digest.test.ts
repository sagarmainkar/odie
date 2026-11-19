import { describe, expect, it } from "vitest";
import { digestShows, learnedLine, loopOf, quietShows, type Digest } from "./digest";

const empty: Digest = { kind: "away", title: "While you were away", text: "", at: "", quiet: [], held: [], changes: [] };

describe("the digest's words", () => {
  it("shows a digest only when it has something", () => {
    expect(digestShows(null)).toBe(false);
    expect(digestShows(empty)).toBe(false);
    expect(digestShows({ ...empty, text: "1 new for you: Gas bill." })).toBe(true);
    expect(digestShows({ ...empty, changes: [{ id: 1, words: "Merged" }] })).toBe(true);
  });
  it("says a learned kind in plain words", () => {
    expect(learnedLine({ id: 1, kind: "promo", acted: 0, of: 6, at: "" })).toBe("promo: in the evening digest (you acted on 0 of 6)");
  });
  it("shows the Quiet section only with a rule or a learned kind", () => {
    expect(quietShows(null)).toBe(false);
    expect(quietShows({ rules: [], learned: [] })).toBe(false);
    expect(quietShows({ rules: [{ id: 1, text: "Fewer", kind: "x", sender: "", at: "" }], learned: [] })).toBe(true);
  });
  it("finds the loop a card's ref names", () => {
    expect(loopOf("loop:12")).toBe(12);
    expect(loopOf("task:3")).toBeNull();
    expect(loopOf("loop:x")).toBeNull();
  });
});
