import { describe, expect, it } from "vitest";
import { pushSub } from "./push";

describe("pushSub", () => {
  it("says each permission state in plain words, for the device in hand", () => {
    expect(pushSub("default", false)).toBe("Off");
    expect(pushSub("denied", true)).toMatch(/iPhone's Settings/);
    expect(pushSub("denied", false)).toMatch(/browser's settings/);
    expect(pushSub("granted", false)).toBe("Allowed: tap Enable to finish");
    expect(pushSub("failed", false)).toBe("Couldn't turn them on. Try again.");
    expect(pushSub("Add Odie to your Home Screen", true)).toBe("Add Odie to your Home Screen");
  });
});
