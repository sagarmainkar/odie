import { describe, expect, it } from "vitest";
import { asksToTurnOn, datelineParts, mastheadDate, mastheadDateLine, onItLine, otherLine, pulseKicker, stillPicked } from "./pulse";
import { followsPick, pickFromHash } from "./pick";
import { railItems } from "./layout";

describe("Pulse", () => {
  it("says what Odie is on in a few words", () => {
    expect(onItLine({ id: 1, title: "app #51", state: "waiting", next: "CI still running" })).toBe("waiting · CI still running");
    expect(onItLine({ id: 2, title: "app #52", state: "new", next: "" })).toBe("starting");
  });

  it("shows the other personalities on Odie's Pulse as a count only", () => {
    expect(otherLine({ id: "abc", name: "Mira", waiting: 2 })).toBe("Mira: 2 waiting");
  });

  it("says whose Pulse it is", () => {
    expect(pulseKicker("", "Wednesday 18 November", "Odie")).toBe("Pulse · Wednesday 18 November");
    expect(pulseKicker("abc", "Wednesday 18 November", "Mira")).toBe("Mira's Pulse · Wednesday 18 November");
  });

  it("asks to turn Proactive intelligence on only when it has an inbox and is off", () => {
    expect(asksToTurnOn({ offered: true, on: false })).toBe(true);
    expect(asksToTurnOn({ offered: true, on: true })).toBe(false);
    expect(asksToTurnOn({ offered: false, on: false })).toBe(false);
    expect(asksToTurnOn(null)).toBe(false);
  });

  it("follows the picked personality", () => {
    expect(followsPick("/api/needs_you")).toBe(true);
    expect(followsPick("/api/needs_you/later")).toBe(true);
    expect(followsPick("/api/loops/3/done")).toBe(true);
    expect(followsPick("/api/watch/seen")).toBe(true);
    expect(followsPick("/api/watch/done")).toBe(true);
    expect(followsPick("/api/tasks/closed_by_watch")).toBe(true);
    expect(followsPick("/api/tasks")).toBe(false);
    expect(followsPick("/api/watch")).toBe(true);  // the chat's count on Back to Pulse is the picked one's
  });

  it("drops an answer that came back after the pick changed", () => {
    expect(stillPicked("abc", "abc")).toBe(true);
    expect(stillPicked("abc", "")).toBe(false);
    expect(stillPicked("", "")).toBe(true);
  });

  it("picks the personality a push opens", () => {
    expect(pickFromHash("#today?personality=abc")).toBe("abc");
    expect(pickFromHash("#today?personality=")).toBe("");
    expect(pickFromHash("#today")).toBe(null);
    expect(pickFromHash("#chat?q=hi")).toBe(null);
  });

  it("is the rail's first tab", () => {
    expect(railItems(null)[0]).toEqual({ tab: "today", label: "Pulse", icon: "sun" });
  });

  it("shows a job going now with its state in words, and Stop rides on it", () => {
    expect(onItLine({ id: "job-3f9a2c", title: "Tides", state: "working", next: "", stop: "job-3f9a2c" })).toBe("working on it");
    expect(onItLine({ id: "job-4a", title: "Other", state: "waiting for a slot", next: "" })).toBe("waiting for a slot");
  });

  it("names the pick on the jobs and recipes calls", () => {
    expect(followsPick("/api/jobs/job-3f9a2c/allow")).toBe(true);
    expect(followsPick("/api/recipes/use")).toBe(true);
  });
});

describe("Newspaper's masthead", () => {
  const day = new Date(2026, 10, 19, 10, 30);
  it("dates the paper in full, in the user's language", () => {
    expect(mastheadDate(day, "en-GB")).toMatch(/^Thursday,? 19 November 2026$/);
    expect(mastheadDate(day, "en-US")).toBe("Thursday, November 19, 2026");
  });
  it("names the personality on its own Pulse, nobody on Odie's", () => {
    expect(mastheadDateLine("", "Thursday, 19 November 2026", "Odie")).toBe("Thursday, 19 November 2026");
    expect(mastheadDateLine("abc", "Thursday, 19 November 2026", "Iris")).toBe("Iris · Thursday, 19 November 2026");
  });
  it("counts what the page holds, leaving out what is nothing", () => {
    expect(datelineParts({ needs: 4, onIt: 1, done: 6 })).toEqual(["4 need you", "1 on it", "6 done today"]);
    expect(datelineParts({ needs: 1, onIt: 0, done: 2 })).toEqual(["1 needs you", "2 done today"]);
    expect(datelineParts({ needs: 0, onIt: 3, done: 0 })).toEqual(["3 on it"]);
    expect(datelineParts({ needs: 0, onIt: 0, done: 0 })).toEqual(["Nothing needs you"]);
  });
});
