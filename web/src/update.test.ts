import { describe, expect, it } from "vitest";
import { checkedAgo, isStale, updateLanded } from "./update";

const H = 60 * 60 * 1000;

describe("checking for an update", () => {
  it("asks again after an hour, or when it never asked", () => {
    expect(isStale(null, 1000)).toBe(true);
    expect(isStale(1000, 1000 + 20 * 60000)).toBe(false);
    expect(isStale(1000, 1000 + H + 60000)).toBe(true);
  });
  it("knows the update landed when the server answers with another version", () => {
    expect(updateLanded("191cd0c", { version: "191cd0c" })).toBe(false);
    expect(updateLanded("191cd0c", { version: "a3f9e01" })).toBe(true);
    expect(updateLanded("191cd0c", null)).toBe(false);
    expect(updateLanded("191cd0c", {})).toBe(false);  // an unpaired answer carries no version
  });
  it("says when it last checked, in plain words", () => {
    expect(checkedAgo(null, 0)).toBe("Not checked yet");
    expect(checkedAgo(1000, 1000 + 20000)).toBe("Checked just now");
    expect(checkedAgo(1000, 1000 + 5 * 60000)).toBe("Checked 5 min ago");
    expect(checkedAgo(1000, 1000 + 2 * H)).toBe("Checked 2 h ago");
  });
});
