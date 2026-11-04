import { describe, expect, it } from "vitest";
import { accentParts, isDayStartChat, isTodaysHello, keepAsking, MORNING_ASK_FOR_MS, shouldShowMorning, weatherTitle, type ChatOnScreen } from "./morning";

describe("the greeting's accent word", () => {
  it("splits the greeting around the word, for the serif italic", () => {
    expect(accentParts("Morning, Asha. Four days to Diwali", "Diwali")).toEqual(["Morning, Asha. Four days to ", "Diwali", ""]);
    expect(accentParts("A quiet Sunday, Asha", "Sunday")).toEqual(["A quiet ", "Sunday", ", Asha"]);
  });

  it("keeps the whole greeting plain when the word isn't in it, or there is none", () => {
    expect(accentParts("Good morning, Asha.", "Diwali")).toEqual(["Good morning, Asha.", "", ""]);
    expect(accentParts("Good morning, Asha.", "")).toEqual(["Good morning, Asha.", "", ""]);
  });
});

describe("where the morning hello is drawn", () => {
  const dayTop: ChatOnScreen = { threadId: null, historyLoaded: true, earlier: 0, cut: false };

  it("asks only from a chat that can start the day: the main view, or the day's first segment", () => {
    expect(isDayStartChat(null, "2026-11-04")).toBe(true);
    expect(isDayStartChat("chat-2026-11-04", "2026-11-04")).toBe(true);
    expect(isDayStartChat("chat-2026-11-04-2", "2026-11-04")).toBe(false);  // a later segment
    expect(isDayStartChat("chat-2026-10-30-5", "2026-11-04")).toBe(false);  // an old thread
  });

  it("shows at the true top of the day, while the hello is ready or being made", () => {
    expect(shouldShowMorning(dayTop, "2026-11-04", "ready")).toBe(true);
    expect(shouldShowMorning(dayTop, "2026-11-04", "making")).toBe(true);
    expect(shouldShowMorning(dayTop, "2026-11-04", "none")).toBe(false);
    expect(shouldShowMorning({ ...dayTop, threadId: "chat-2026-11-04" }, "2026-11-04", "ready")).toBe(true);
  });

  it("never shows after a /new, above unloaded messages, or before the history answers", () => {
    expect(shouldShowMorning({ ...dayTop, cut: true }, "2026-11-04", "ready")).toBe(false);
    expect(shouldShowMorning({ ...dayTop, earlier: 30 }, "2026-11-04", "ready")).toBe(false);
    expect(shouldShowMorning({ ...dayTop, historyLoaded: false }, "2026-11-04", "ready")).toBe(false);
  });

  it("never shows in a later segment or an old thread", () => {
    expect(shouldShowMorning({ ...dayTop, threadId: "chat-2026-11-04-2" }, "2026-11-04", "ready")).toBe(false);
    expect(shouldShowMorning({ ...dayTop, threadId: "chat-2026-10-30-5" }, "2026-11-04", "ready")).toBe(false);
  });
});

describe("asking again while the hello is made", () => {
  it("asks again while it's being made, for up to three minutes", () => {
    expect(keepAsking("making", 0, 30_000)).toBe(true);
    expect(keepAsking("making", 0, MORNING_ASK_FOR_MS)).toBe(false);
    expect(keepAsking("ready", 0, 10_000)).toBe(false);
    expect(keepAsking("none", 0, 10_000)).toBe(false);
  });
});

describe("the weather strip's title", () => {
  it("says the sky and the place, or whichever it has", () => {
    const w = { place: "Pune", now_c: 27, high_c: 31, low_c: 19, words: "Clear" };
    expect(weatherTitle(w)).toBe("Clear in Pune");
    expect(weatherTitle({ ...w, place: "" })).toBe("Clear");
    expect(weatherTitle({ ...w, words: "" })).toBe("Today in Pune");
    expect(weatherTitle({ ...w, place: "", words: "" })).toBe("Today");
  });
});

describe("whose day the hello is", () => {
  it("draws only today's hello, not yesterday's between midnight and five", () => {
    expect(isTodaysHello({ state: "ready", day: "2026-11-04", card: null }, "2026-11-04")).toBe(true);
    expect(isTodaysHello({ state: "ready", day: "2026-11-04", card: null }, "2026-11-05")).toBe(false);  // 01:30 on 5 Nov
  });
});
