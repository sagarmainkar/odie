import { describe, expect, it } from "vitest";
import { smallModelLine } from "./providers";

const name = (id: string) => ({ ollama: "Ollama", lmstudio: "LM Studio" })[id] ?? id;

describe("the small model for Workers, in words", () => {
  it("says who picked it", () => {
    expect(smallModelLine({ provider: "ollama", model: "lfm3:latest", chosen: false, auto: true }, name)).toBe("lfm3:latest · picked by Odie (Ollama had it)");
    expect(smallModelLine({ provider: "lmstudio", model: "gemma-4-26b", chosen: true, auto: false }, name)).toBe("gemma-4-26b · your pick");
  });
  it("falls back to the chat model in words", () => {
    expect(smallModelLine({ provider: null, model: null, chosen: false, auto: false }, name)).toBe("Same as the chat model · pick a small local one below");
  });
});
