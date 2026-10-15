import { describe, expect, it } from "vitest";
import { addressHint, creativityLabel, providerSub, visibleModels } from "./providers";

const ms = (ids: string[]) => ids.map((id) => ({ id, local: false }));

describe("visibleModels", () => {
  const many = ms(Array.from({ length: 30 }, (_, i) => `vendor/model-${i}`));
  it("shows short lists whole", () => {
    expect(visibleModels(ms(["a", "b"]), "", 12)).toEqual({ shown: ms(["a", "b"]), hidden: 0 });
  });
  it("cuts long lists but keeps the chosen model", () => {
    const r = visibleModels(many, "", 12, "vendor/model-25");
    expect(r.shown[0].id).toBe("vendor/model-25");
    expect(r.shown.length).toBe(13);
    expect(r.hidden).toBe(17);
  });
  it("filters by any part of the id, ignoring case", () => {
    const r = visibleModels(ms(["anthropic/claude-opus-5-5", "z-ai/glm-5.3", "openai/gpt-5.5"]), "GLM", 12);
    expect(r.shown.map((m) => m.id)).toEqual(["z-ai/glm-5.3"]);
  });
});

describe("providerSub", () => {
  it("says what each row means", () => {
    expect(providerSub({ id: "lmstudio", name: "LM Studio", kind: "local", connected: true })).toBe("Running on this computer");
    expect(providerSub({ id: "ollama", name: "Ollama", kind: "local", connected: false })).toBe("Not running on this computer");
    expect(providerSub({ id: "gemini", name: "Gemini", kind: "preset", connected: false })).toMatch(/Add a key/);
    expect(providerSub({ id: "openai", name: "OpenAI", kind: "preset", connected: true })).toMatch(/voices/);
  });
});

describe("addressHint", () => {
  it("names the .env line for a built-in provider and Settings for a custom one", () => {
    expect(addressHint({ base_url: "http://localhost:11434/v1", base_url_env: "OLLAMA_BASE_URL" })).toBe("another address: see the setup guide");
    expect(addressHint({ base_url: "https://api.example/v1", base_url_env: null })).toBe("change it in Settings → Providers");
    expect(addressHint({})).toBeNull();
  });
});

describe("creativityLabel", () => {
  it("gives the temperature with a word for it", () => {
    expect(creativityLabel(0.7)).toBe("0.7 · balanced");
    expect(creativityLabel(0)).toBe("0.0 · steady");
    expect(creativityLabel(1.2)).toBe("1.2 · inventive");
  });
});
