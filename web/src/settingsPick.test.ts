import { describe, expect, it } from "vitest";
import { avatarUrl, deleteWords, personaUrl, showsDelete, showsWhoLine, soulUrl, whoLine } from "./settingsPick";

describe("Settings follows the picked personality", () => {
  it("reads and saves the name, the picture and the personality of whoever is picked", () => {
    expect(personaUrl("abc")).toBe("/api/persona?personality=abc");
    expect(avatarUrl("abc")).toBe("/api/persona/avatar?personality=abc");
    expect(soulUrl("abc")).toBe("/api/soul?personality=abc");
  });

  it("says so for everyday Odie too, with an empty pick", () => {
    expect(personaUrl("")).toBe("/api/persona?personality=");
    expect(soulUrl("")).toBe("/api/soul?personality=");
  });

  it("offers Delete for a personality, never for Odie", () => {
    expect(showsDelete("abc")).toBe(true);
    expect(showsDelete("")).toBe(false);
  });

  it("says who is being edited once there is someone else to edit", () => {
    expect(showsWhoLine("", 0)).toBe(false);  // no personalities: Settings looks as it always has
    expect(showsWhoLine("", 2)).toBe(true);
    expect(showsWhoLine("abc", 1)).toBe(true);
    expect(whoLine("Mira")).toBe("Editing Mira");
  });

  it("asks before deleting, in words that say what goes and what Odie can't reach", () => {
    const rest = " Its threads, memory, instructions and picture are erased for good. Not erased: debug copies of recent model "
      + "requests (they age out on their own), log lines, and anything already sent to a tracing service.";
    expect(deleteWords("Mira", 4)).toBe("Delete Mira and its 4 threads?" + rest);
    expect(deleteWords("Mira", 1)).toBe("Delete Mira and its 1 thread?" + rest);
    expect(deleteWords("Mira", 0)).toBe("Delete Mira?" + rest);
  });
});
