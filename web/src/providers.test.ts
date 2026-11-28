import { describe, expect, it } from "vitest";
import { addressEditable, addressHint, answerLine, creativityLabel, hostAndPort, movedAddress, providerSub, shouldTestBeforeSave,
  visibleModels, type ProviderInfo } from "./providers";

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
  it("sends every provider's address to Settings", () => {
    expect(addressHint({ base_url: "http://localhost:11434/v1" })).toBe("change it in Settings → Providers");
    expect(addressHint({ base_url: "https://api.example/v1" })).toBe("change it in Settings → Providers");
    expect(addressHint({})).toBeNull();
  });
});

const lmStudio: ProviderInfo = { id: "lmstudio", name: "LM Studio", kind: "local", connected: true,
  base_url: "http://localhost:1234/v1", default_url: "http://localhost:1234/v1", address_from_env: false };

describe("a provider's address", () => {
  it("names a moved local provider by its computer and port", () => {
    expect(providerSub({ ...lmStudio, base_url: "http://localhost:1235/v1" })).toBe("Running at localhost:1235");
    expect(providerSub({ ...lmStudio, base_url: "http://studio.local:1234/v1", connected: false })).toBe("Not answering at studio.local:1234");
    expect(providerSub(lmStudio)).toBe("Running on this computer");
    expect(hostAndPort("not an address")).toBe("not an address");
  });
  it("offers Reset only when a built-in one was moved", () => {
    expect(movedAddress(lmStudio)).toBe(false);
    expect(movedAddress({ ...lmStudio, base_url: "http://localhost:1235/v1" })).toBe(true);
    expect(movedAddress({ id: "mine", name: "Mine", kind: "custom", connected: true, base_url: "http://a.local/v1" })).toBe(false);
  });
  it("can't be edited when Odie's environment sets it", () => {
    expect(addressEditable(lmStudio)).toBe(true);
    expect(addressEditable({ ...lmStudio, address_from_env: true })).toBe(false);
    expect(addressEditable({ id: "mine", name: "Mine", kind: "custom", connected: true })).toBe(true);
  });
  it("says whether it answers", () => {
    expect(answerLine(null)).toBe("");
    expect(answerLine({ ok: true, models: 12, problem: null })).toBe("Answers · 12 models");
    expect(answerLine({ ok: true, models: 1, problem: null })).toBe("Answers · 1 model");
    expect(answerLine({ ok: true, models: 0, problem: null })).toBe("Answers · no chat models loaded");
    expect(answerLine({ ok: false, models: null, problem: "Nothing answers at that address." })).toBe("Nothing answers at that address.");
  });
  it("tests a changed address once before saving, then saves anyway", () => {
    const saved = "http://localhost:1234/v1";
    expect(shouldTestBeforeSave(saved, saved, null)).toBe(false);
    expect(shouldTestBeforeSave("http://localhost:1234/v1/", saved, null)).toBe(false);
    expect(shouldTestBeforeSave("http://localhost:1235/v1", saved, null)).toBe(true);
    expect(shouldTestBeforeSave("http://localhost:1235/v1", saved, "http://localhost:1235/v1")).toBe(false);
    expect(shouldTestBeforeSave("http://localhost:1236/v1", saved, "http://localhost:1235/v1")).toBe(true);
  });
});

describe("creativityLabel", () => {
  it("gives the temperature with a word for it", () => {
    expect(creativityLabel(0.7)).toBe("0.7 · balanced");
    expect(creativityLabel(0)).toBe("0.0 · steady");
    expect(creativityLabel(1.2)).toBe("1.2 · inventive");
  });
});
