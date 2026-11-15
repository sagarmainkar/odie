import { describe, expect, it } from "vitest";
import { madeWords, modelChoices, modelFrom, modelValue, modelWords, type Bot } from "./bots";

const bot = (over: Partial<Bot>): Bot => ({ name: "researcher", role: "finds", prompt: "", model: null, powers: [], made_by: "chief", edited_by_user: false, chief: false, ...over });

describe("bots", () => {
  it("names a model and round-trips the picker's value", () => {
    expect(modelWords(null)).toBe("Chat model");
    expect(modelWords({ provider: "ollama", model: "lfm3:latest" })).toBe("lfm3:latest · ollama");
    expect(modelValue(null)).toBe("");
    expect(modelFrom("")).toBeNull();
    expect(modelFrom("ollama|lfm3:latest")).toEqual({ provider: "ollama", model: "lfm3:latest" });
    expect(modelFrom("openrouter|a|b")).toEqual({ provider: "openrouter", model: "a|b" });
  });

  it("offers the chat model, the reachable providers' models, and keeps an unlisted pick", () => {
    const providers = [
      { id: "ollama", name: "Ollama", models: [{ id: "lfm3:latest" }], error: null },
      { id: "lmstudio", name: "LM Studio", models: [{ id: "gemma" }], error: "down" },
    ];
    expect(modelChoices(providers, null).map((c) => c.value)).toEqual(["", "ollama|lfm3:latest"]);
    const gone = modelChoices(providers, { provider: "lmstudio", model: "gemma" });
    expect(gone.at(-1)).toEqual({ value: "lmstudio|gemma", label: "gemma · lmstudio (not listed now)" });
  });

  it("says who a bot belongs to", () => {
    expect(madeWords(bot({ chief: true }))).toBe("always here");
    expect(madeWords(bot({ edited_by_user: true }))).toBe("yours");
    expect(madeWords(bot({}))).toBe("made by the chief");
  });
});
