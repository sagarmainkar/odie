import { describe, expect, it } from "vitest";
import { bandsFor, isNowEvent, parseCalendar } from "./Today";

describe("parseCalendar", () => {
  it("splits today's and tomorrow's events from a calendar app's text", () => {
    const raw = "## 2026-10-01\na1 | 09:30-10:00 | Standup | team@x\n## 2026-10-02\nb2 | all day 2026-10-02 | Team offsite";
    const c = parseCalendar(raw, "2026-10-01", "2026-10-02")!;
    expect(c.today).toEqual([{ time: "09:30", end: "10:00", title: "Standup" }]);
    expect(c.tomorrow).toEqual([{ time: "All day", title: "Team offsite" }]);
  });
  it("treats 'No events' as a clear day and null as not connected", () => {
    expect(parseCalendar("No events from 2026-10-01 to 2026-10-02.", "2026-10-01", "2026-10-02")).toEqual({ today: [], tomorrow: [] });
    expect(parseCalendar(null, "2026-10-01", "2026-10-02")).toBeNull();
  });
});

describe("bandsFor", () => {
  it("splits events at noon and 5 pm; all-day goes to morning", () => {
    const b = bandsFor([{ time: "09:30", title: "a" }, { time: "12:00", title: "b" }, { time: "16:59", title: "c" }, { time: "17:00", title: "d" }, { time: "All day", title: "e" }]);
    expect(b.morning.map((e) => e.title)).toEqual(["a", "e"]);
    expect(b.afternoon.map((e) => e.title)).toEqual(["b", "c"]);
    expect(b.evening.map((e) => e.title)).toEqual(["d"]);
  });
});

describe("isNowEvent", () => {
  it("is now only between start and end", () => {
    const e = { time: "08:00", end: "08:30", title: "a" };
    expect(isNowEvent(e, "08:10")).toBe(true);
    expect(isNowEvent(e, "09:00")).toBe(false);
    expect(isNowEvent(e, "07:59")).toBe(false);
  });
  it("all-day events are never outlined", () => {
    expect(isNowEvent({ time: "All day", title: "b" }, "12:00")).toBe(false);
  });
});
