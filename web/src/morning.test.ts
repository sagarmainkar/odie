import { describe, expect, it } from "vitest";
import { accentParts, isTodaysChat, keepAsking, MORNING_ASK_FOR_MS, shouldShowMorning, weatherTitle } from "./morning";

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
  it("is today's chat: the main view, or one of today's segments opened from Threads", () => {
    expect(isTodaysChat(null, "2026-11-04")).toBe(true);
    expect(isTodaysChat("chat-2026-11-04-2", "2026-11-04")).toBe(true);
    expect(isTodaysChat("chat-2026-10-30-5", "2026-11-04")).toBe(false);
  });

  it("shows while the hello is ready or being made, in today's chat only", () => {
    expect(shouldShowMorning(null, "2026-11-04", "ready")).toBe(true);
    expect(shouldShowMorning(null, "2026-11-04", "making")).toBe(true);
    expect(shouldShowMorning(null, "2026-11-04", "none")).toBe(false);
    expect(shouldShowMorning("chat-2026-11-04", "2026-11-04", "ready")).toBe(true);
    expect(shouldShowMorning("chat-2026-10-30-5", "2026-11-04", "ready")).toBe(false);  // an old thread
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
