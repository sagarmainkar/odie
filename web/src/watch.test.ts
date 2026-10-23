import { describe, expect, it } from "vitest";
import { badge, footer, type WatchCardData } from "./watch";

const card = (over: Partial<WatchCardData> = {}): WatchCardData => ({
  checked_at: "2026-10-08T14:30:00+05:30", line: "2 new emails", needs_you: [], events: [], unseen: 0,
  sources: { "mail:zapier": { ok: true, app: "Zapier", kind: "mail" }, "calendar:zapier": { ok: true, app: "Zapier", kind: "calendar" } }, ...over,
});

describe("watch", () => {
  it("says when it checked, through what, and when it checks next", () => {
    expect(footer(card(), new Date("2026-10-08T14:31:00+05:30"))).toBe("checked 14:30 via Zapier · next 15:00");
  });
  it("says what's failing instead", () => {
    const c = card({ sources: { "mail:zapier": { ok: false, app: "Zapier", kind: "mail", reason: "401 Unauthorized" } } });
    expect(footer(c, new Date())).toBe("Zapier (mail) isn't working");
    const cal = card({ sources: { "calendar:mac": { ok: false, app: "Calendar", kind: "calendar", reason: "-600" } } });
    expect(footer(cal, new Date())).toBe("Calendar isn't working");
  });
  it("counts up to 9+", () => {
    expect(badge(0)).toBe("");
    expect(badge(3)).toBe("3");
    expect(badge(12)).toBe("9+");
  });
});
