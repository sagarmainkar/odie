import { describe, expect, it } from "vitest";
import { busyDates, dateParts, dayEvents, relative, subline, timeText, type UpItem } from "./upnext";

const item = (o: Partial<UpItem>): UpItem => ({ id: "x", source: "calendar", sources: ["calendar"], kind: "general", title: "T", date: "2026-10-05",
  time: null, end: null, place: null, people: null, amount: null, ask: "", ...o });
const NOW = new Date(2026, 9, 5, 9, 30);

describe("up next", () => {
  it("says when, relative to now", () => {
    expect(relative(item({ time: "09:55" }), NOW)).toBe("In 25 min");
    expect(relative(item({ time: "12:30" }), NOW)).toBe("In 3 h");
    expect(relative(item({}), NOW)).toBe("Today");
    expect(relative(item({ date: "2026-10-06" }), NOW)).toBe("Tomorrow");
    expect(relative(item({ date: "2026-10-08" }), NOW)).toBe("In 3 days");
    expect(relative(item({ date: "2026-10-12" }), NOW)).toBe("In 1 week");
    expect(relative(item({ date: "2026-10-19" }), NOW)).toBe("In 2 weeks");
  });
  it("draws the date card and lines", () => {
    expect(dateParts("2026-10-08")).toMatchObject({ day: 8, weekday: "Thursday" });
    expect(timeText(item({ time: "18:30", end: "19:15" }))).toBe("18:30–19:15");
    expect(timeText(item({}))).toBe("All day");
    expect(timeText(item({ kind: "delivery", title: "Amazon order ••3334 · shipped" }))).toBe("On the way");
    expect(timeText(item({ kind: "delivery", title: "Nykaa order ••ONE1 · delivered" }))).toBe("Delivered");
    expect(subline(item({ amount: 12340 }))).toBe("₹12,340 due");
    expect(subline(item({ place: "Ruby Hall Clinic" }))).toBe("Ruby Hall Clinic");
    expect(subline(item({ people: ["asha@x.com"] }))).toBe("asha");
  });
  it("feeds the week strip and day bands", () => {
    const items = [item({ date: "2026-10-05", time: "18:30", end: "19:15", title: "Dr" }), item({ date: "2026-10-07", title: "Bday" })];
    expect([...busyDates(items)]).toEqual(["2026-10-05", "2026-10-07"]);
    expect(dayEvents(items, "2026-10-05")).toEqual([{ time: "18:30", end: "19:15", title: "Dr" }]);
    expect(dayEvents(items, "2026-10-07")).toEqual([{ time: "All day", title: "Bday" }]);
  });
});
