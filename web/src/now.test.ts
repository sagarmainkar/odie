import { describe, expect, it } from "vitest";
import { canAdd, cleanLines, moveLine, saveReady, withoutLine } from "./now";

describe("the Now list's editing", () => {
  it("keeps his lines trimmed and leaves blanks out", () => {
    expect(cleanLines(["  Ship   Odie ", "", "  ", "Run"])).toEqual(["Ship Odie", "Run"]);
  });
  it("saves at most seven lines, none too long; an empty list clears it", () => {
    expect(saveReady(Array(7).fill("x"), 7)).toBe(true);
    expect(saveReady(Array(8).fill("x"), 7)).toBe(false);
    expect(saveReady(["x".repeat(121)], 7)).toBe(false);
    expect(saveReady([], 7)).toBe(true);
    expect(saveReady([...Array(7).fill("x"), ""], 7)).toBe(true);  // a blank line isn't one
  });
  it("adds a line only while there is room", () => {
    expect(canAdd(Array(6).fill("x"), 7)).toBe(true);
    expect(canAdd(Array(7).fill("x"), 7)).toBe(false);
  });
  it("moves a line up or down, never past either end", () => {
    expect(moveLine(["a", "b", "c"], 2, -1)).toEqual(["a", "c", "b"]);
    expect(moveLine(["a", "b", "c"], 0, 1)).toEqual(["b", "a", "c"]);
    expect(moveLine(["a", "b"], 0, -1)).toEqual(["a", "b"]);
    expect(moveLine(["a", "b"], 1, 1)).toEqual(["a", "b"]);
  });
  it("takes a line out", () => {
    expect(withoutLine(["a", "b", "c"], 1)).toEqual(["a", "c"]);
  });
});
