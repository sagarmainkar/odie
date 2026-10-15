import { describe, expect, it } from "vitest";
import type { Media } from "./media";
import { autoplayFor } from "./reminders";

const memo: Media = { id: "0123456789abcdef", kind: "memo", title: "Reminder: Stretch", mime: "audio/wav", size: 1, created: 1 };

describe("spoken reminders", () => {
  it("plays a reminder's memo when it arrives, if Odie is open and nothing else is playing", () => {
    expect(autoplayFor({ type: "message", text: "Reminder: Stretch", media: [memo] }, true, false)).toBe(memo.id);
    expect(autoplayFor({ type: "message", text: "Reminder: Stretch", media: [memo] }, false, false)).toBeNull();  // hidden
    expect(autoplayFor({ type: "message", text: "Reminder: Stretch", media: [memo] }, true, true)).toBeNull();  // a podcast is on
    expect(autoplayFor({ type: "message", text: "Reminder: Stretch" }, true, false)).toBeNull();  // the setting is off: no memo
    expect(autoplayFor({ type: "message", text: "x", media: [{ ...memo, kind: "podcast" }] }, true, false)).toBeNull();
    expect(autoplayFor({ type: "task", media: [memo] }, true, false)).toBeNull();
  });
});
