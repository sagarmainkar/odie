import { describe, expect, it } from "vitest";
import { ago, everyText, ordered, pageText, type Tracker } from "./trackers";

const t = (o: Partial<Tracker>): Tracker => ({ id: 1, title: "x", check_text: "", status: "active", schedule: { minutes: 15 }, notify: "change", condition: "",
  last_summary: null, last_checked_at: null, next_check_at: "", until_at: "", blocks: null, fails: 0, page_url: null, signin_allowed: 0, ...o });

describe("trackers", () => {
  it("says how often", () => {
    expect(everyText({ minutes: 15 })).toBe("every 15 min");
    expect(everyText({ minutes: 120 })).toBe("every 2 h");
    expect(everyText({ minutes: 1440 })).toBe("every day");
    expect(everyText({ times: ["09:00"], days: null })).toBe("daily 09:00");
    expect(everyText({ times: ["07:30"], days: [0, 1, 2, 3, 4] })).toBe("weekdays 07:30");
    expect(everyText({ times: ["09:00"], days: [0] })).toBe("Mon 09:00");
  });
  it("says when it last checked", () => {
    const now = Date.parse("2026-10-05T10:00:00Z");
    expect(ago(null, now)).toBe("not checked yet");
    expect(ago("2026-10-05T09:48:00+00:00", now)).toBe("12 min ago");
    expect(ago("2026-10-05T07:00:00+00:00", now)).toBe("3 h ago");
  });
  it("orders active, paused, then finished; hides stopped", () => {
    const r = ordered([t({ id: 1, status: "done" }), t({ id: 2, status: "paused" }), t({ id: 3 }), t({ id: 4, status: "stopped" })]);
    expect(r.map((x) => x.id)).toEqual([3, 2, 1]);
  });
  it("shows a page without its scheme, www or query", () => {
    expect(pageText("https://www.amazon.in/gp/your-account/order-history?ref_=nav")).toBe("amazon.in/gp/your-account/order-history");
    expect(pageText("https://amazon.in/")).toBe("amazon.in");
    expect(pageText("not a url")).toBe("not a url");
  });
});
