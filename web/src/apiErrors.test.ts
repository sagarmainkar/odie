import { describe, expect, it } from "vitest";
import { errorWords } from "./api";

describe("A call the server refused says why", () => {
  it("uses the server's own words, such as a tap on a card whose brain is no longer set up", () => {
    const words = "Mira's brain (qwen on work-box) isn't set up any more, so Mira can't answer.";
    expect(errorWords(409, { detail: words })).toBe(words);
  });

  it("falls back to the status when the server gave no words", () => {
    expect(errorWords(500, null)).toBe("HTTP 500");
    expect(errorWords(422, { detail: [{ msg: "field required" }] })).toBe("HTTP 422");
  });
});
