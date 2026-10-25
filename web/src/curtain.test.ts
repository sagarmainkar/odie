import { describe, expect, it } from "vitest";
import { memoToPlay, snoozeChoices, withNotice, withoutNotice, type Notice } from "./curtain";

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

describe("snoozing a reminder", () => {
  it("offers an hour, three hours and tomorrow morning", () => {
    const now = new Date(2026, 9, 25, 18, 20); // 25 Oct, 18:20 local time
    const choices = snoozeChoices(now);
    expect(choices.map((c) => c.label)).toEqual(["1 hour", "3 hours", "Tomorrow 9:00"]);
    expect(new Date(choices[0].until).getTime() - now.getTime()).toBe(60 * 60 * 1000);
    expect(new Date(choices[1].until).getTime() - now.getTime()).toBe(3 * 60 * 60 * 1000);
    const tomorrow = new Date(choices[2].until);
    expect([tomorrow.getDate(), tomorrow.getHours(), tomorrow.getMinutes()]).toEqual([26, 9, 0]);
  });
  it("means the morning ahead in the small hours", () => {
    const morning = new Date(snoozeChoices(new Date(2026, 9, 26, 0, 30))[2].until);
    expect([morning.getDate(), morning.getHours()]).toEqual([26, 9]);
    const later = new Date(snoozeChoices(new Date(2026, 9, 26, 5, 0))[2].until);
    expect([later.getDate(), later.getHours()]).toEqual([27, 9]);
  });
});
