import { describe, expect, it } from "vitest";
import { SKINS, faceFor, faceKind } from "./faces";

const names = ["Claire", "Tom", "Narrator", "The keeper", "Ada", "Captain", "Witch", "Boy", "Girl", "Ghost", "Fox", "Owl",
  "Mira", "Jonah", "Priya", "Ravi", "Elena", "Kofi", "Hana", "Leo"];

describe("a face for each name", () => {
  it("is the same every time for the same name", () => {
    expect(faceFor("Claire", "female")).toEqual(faceFor("Claire", "female"));
    expect(faceFor(" Claire ", "female")).toEqual(faceFor("Claire", "female"));  // stray spaces don't change it
  });

  it("is a woman's, a man's or a storybook face by group", () => {
    expect(faceKind("female")).toBe("woman");
    expect(faceKind("male")).toBe("man");
    expect(faceKind("Characters")).toBe("storybook");
    expect(faceKind("")).toBe("storybook");  // an unknown group gets the neutral face
    expect(faceFor("Claire", "female").kind).toBe("woman");
    expect(faceFor("Tom", "male").kind).toBe("man");
    expect(faceFor("Fox", "Characters").kind).toBe("storybook");
  });

  it("varies across a cast: hair, skin and accessory come from the name", () => {
    const women = names.map((n) => faceFor(n, "female"));
    expect(new Set(women.map((f) => f.hair)).size).toBeGreaterThan(2);
    expect(new Set(women.map((f) => f.skin)).size).toBeGreaterThan(2);
    expect(new Set(women.map((f) => f.extra)).size).toBeGreaterThan(1);
    for (const f of women) expect(SKINS).toContain(f.skin);
  });
});
