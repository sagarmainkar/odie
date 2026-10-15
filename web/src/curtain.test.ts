import { describe, expect, it } from "vitest";
import { memoToPlay, withNotice, withoutNotice, type Notice } from "./curtain";

const a: Notice = { id: 3, text: "Reminder: Pay Lily's fees", kind: "reminder" };
const b: Notice = { id: 4, text: "Due now: Power bill", kind: "due" };

describe("the reminder curtain's queue", () => {
  it("keeps notices in the order they came and never the same one twice", () => {
    expect(withNotice([], a)).toEqual([a]);
    expect(withNotice([a], a)).toEqual([a]);
    expect(withNotice([a], b)).toEqual([a, b]);
  });
  it("drops the one that was answered", () => {
    expect(withoutNotice([a, b], 3)).toEqual([b]);
    expect(withoutNotice([a], 9)).toEqual([a]);
  });
  it("plays the spoken memo only when the app is on screen and quiet", () => {
    const spoken: Notice = { ...a, media: [{ id: "m1", kind: "memo" } as never] };
    expect(memoToPlay(spoken, true, false)).toBe("m1");
    expect(memoToPlay(spoken, false, false)).toBeNull();
    expect(memoToPlay(spoken, true, true)).toBeNull();
    expect(memoToPlay(a, true, false)).toBeNull();
  });
});
