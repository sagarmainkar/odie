import { describe, expect, it } from "vitest";
import { bandsFor, closedTodayCount, isNowEvent, parseCalendar, taskRow, taskTile } from "./Today";

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

describe("closedTodayCount", () => {
  it("is 0 when the server doesn't have the route yet", async () => {
    expect(await closedTodayCount(() => Promise.reject(new Error("404")))).toBe(0);
    expect(await closedTodayCount(() => Promise.resolve({ count: 3 }))).toBe(3);
  });
});

describe("taskTile", () => {
  it("colours by source", () => {
    expect(taskTile({ source_kind: "ledger" })).toEqual({ icon: "rupee", color: "green" });
    expect(taskTile({ source_kind: "mail" })).toEqual({ icon: "mail", color: "blue" });
    expect(taskTile({ source_kind: null })).toEqual({ icon: "bell", color: "violet" });
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

describe("taskRow", () => {
  const base = { id: 1, kind: "followup", status: "open", due_at: null, next_check_at: null };
  it("draws a mail thread as the chat's mail row and opens the email on tap", () => {
    const row = taskRow({ ...base, title: "Reply to Priya Nair: Can we move our 1:1?", source_kind: "mail",
                          detail: "from Priya Nair <priya@acme.example>\nCould we move to Thursday?" });
    expect(row.title).toBe("Priya Nair · Can we move our 1:1?");
    expect(row.lead).toMatchObject({ kind: "initial", letter: "P" });
    expect(row.subtitle).toBe(":badge[Reply] Could we move to Thursday?");
    expect(row.run).toBe("Open the email from Priya Nair about Can we move our 1:1?");
  });
  it("a mail thread with no gist shows the badge alone", () => {
    const row = taskRow({ ...base, title: "Reply to Asha Rao: Dinner Saturday?", source_kind: "mail", detail: "from Asha Rao <a@x>" });
    expect(row.subtitle).toBe(":badge[Reply]");
  });
  it("a due from the ledger keeps its rupee tile and gets a Due badge with the day", () => {
    const row = taskRow({ ...base, title: "Pay the electricity bill", source_kind: "ledger", due_at: "2030-01-05" });
    expect(row.lead).toEqual({ kind: "tile", icon: "rupee", color: "green" });
    expect(row.subtitle).toMatch(/^:badge\[Due\] \S.* · from your messages$/);
    expect(row.subtitle).not.toContain("Due Due");
    expect(row.run).toBe("Tell me about: Pay the electricity bill");
  });
  it("a reminder keeps its bell; one that has fired says Now", () => {
    const quiet = taskRow({ ...base, title: "Call Ravi", kind: "reminder", due_at: "2030-01-05T17:00" });
    expect(quiet.lead).toEqual({ kind: "tile", icon: "bell", color: "violet" });
    expect(quiet.subtitle.startsWith("Due ")).toBe(true);
    const fired = taskRow({ ...base, title: "Call Ravi", kind: "reminder", due_at: "2030-01-05T17:00", delivered_at: "2030-01-05T17:00" });
    expect(fired.subtitle.startsWith(":badge[Now]{warn} Due ")).toBe(true);
  });
});
