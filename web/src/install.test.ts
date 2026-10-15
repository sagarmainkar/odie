import { describe, expect, it } from "vitest";
import { isPhone, shouldNudge } from "./install";

describe("install nudge", () => {
  it("shows only in a phone's browser, until dismissed", () => {
    expect(shouldNudge({ standalone: false, phone: true, dismissed: false })).toBe(true);
    expect(shouldNudge({ standalone: true, phone: true, dismissed: false })).toBe(false);  // already the home-screen app
    expect(shouldNudge({ standalone: false, phone: false, dismissed: false })).toBe(false);  // a laptop's browser is fine
    expect(shouldNudge({ standalone: false, phone: true, dismissed: true })).toBe(false);
  });

  it("knows a phone from its user agent", () => {
    expect(isPhone("Mozilla/5.0 (iPhone; CPU iPhone OS 19_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1")).toBe(true);
    expect(isPhone("Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 Chrome/141.0 Mobile Safari/537.36")).toBe(true);
    expect(isPhone("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15")).toBe(false);
  });
});
