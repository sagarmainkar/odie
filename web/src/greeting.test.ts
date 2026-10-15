import { describe, expect, it } from "vitest";
import { greeting, greetingParts } from "./greeting";

describe("greetingParts", () => {
  it("names the part of the day as the accent word", () => {
    expect(greetingParts(8)).toEqual({ lead: "Good", accent: "morning" });
    expect(greetingParts(13)).toEqual({ lead: "Good", accent: "afternoon" });
    expect(greetingParts(20)).toEqual({ lead: "Good", accent: "evening" });
    expect(greetingParts(2)).toEqual({ lead: "Still", accent: "up" });
  });
  it("adds the name when there is one", () => {
    expect(greeting(9, "Asha")).toBe("Good morning, Asha.");
    expect(greeting(9)).toBe("Good morning.");
  });
});
