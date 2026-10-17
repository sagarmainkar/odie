import { describe, expect, it } from "vitest";
import { stepsSummary, toolLabel } from "./Steps";

describe("steps", () => {
  it("labels by tense", () => {
    expect(toolLabel({ name: "gmail_search", done: false })).toBe("Searching mail");
    expect(toolLabel({ name: "gmail_search", done: true })).toBe("Searched mail");
    expect(toolLabel({ name: "mystery", done: true })).toBe("Used mystery");          // never a raw id
    expect(toolLabel({ name: "GMAIL_FETCH_EMAILS", done: false })).toBe("Using gmail fetch emails");
    expect(toolLabel({ name: "load_skill", done: true })).toBe("Loaded a skill");
    expect(toolLabel({ name: "find_clips", done: false })).toBe("Finding clips");
    expect(toolLabel({ name: "find_clips", done: true })).toBe("Found clips");
  });
  it("summarises unique steps", () => {
    expect(stepsSummary([{ name: "gmail_search", done: true }, { name: "gmail_search", done: true }, { name: "calendar_list_events", done: true }]))
      .toBe("Searched mail, checked calendar");
  });
});
