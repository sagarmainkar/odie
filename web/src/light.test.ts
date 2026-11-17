import { describe, expect, it } from "vitest";
import { LIGHTS, lightOf } from "./light";

describe("each personality has a light of its own", () => {
  it("everyday Odie has none: the wash follows the time of day", () => {
    expect(lightOf("")).toBe(0);
  });

  it("a personality always gets the same one of the six", () => {
    const first = lightOf("980a3305d04e");
    expect(first).toBeGreaterThanOrEqual(1);
    expect(first).toBeLessThanOrEqual(LIGHTS.length);
    expect(lightOf("980a3305d04e")).toBe(first);
  });

  it("different personalities are spread over the six", () => {
    const ids = ["a1", "b2", "c3", "d4", "e5", "f6", "g7", "h8", "i9", "j0", "k1", "l2"];
    const seen = new Set(ids.map(lightOf));
    expect(seen.size).toBeGreaterThanOrEqual(4);
  });
});
