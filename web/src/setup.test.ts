import { describe, expect, it } from "vitest";
import { brainDone, canSkip, chipState, firstPick, formFor, keyRoute, type Panel, type SetupState } from "./setup";

const s: SetupState = {
  done: false, current: "vault", thread: [],
  steps: { brain: "done", names: "done", vault: "todo", embeddings: "todo", photos: "todo", search: "skipped", voice: "todo", apps: "todo", phone: "todo" },
};

describe("setup", () => {
  it("draws each chip from the checklist", () => {
    expect(chipState("brain", s)).toBe("done");
    expect(chipState("vault", s)).toBe("current");
    expect(chipState("search", s)).toBe("skipped");
    expect(chipState("voice", s)).toBe("todo");
  });

  it("sends each key to its own route", () => {
    expect(keyRoute({ type: "key", provider: "openai", kind: "provider", label: "OpenAI", note: "" })).toBe("/api/providers/openai/key");
    expect(keyRoute({ type: "key", provider: "tavily", kind: "search", label: "Tavily", note: "" })).toBe("/api/search/tavily/key");
  });

  it("lets a checked brain through, unless it failed", () => {
    expect(brainDone(undefined)).toBe(false);
    expect(brainDone({ verdict: "good" })).toBe(true);
    expect(brainDone({ verdict: "slow" })).toBe(true);
    expect(brainDone({ verdict: "warn" })).toBe(true);
    expect(brainDone({ verdict: "fail" })).toBe(false);
  });

  it("never skips the brain or the names", () => {
    expect(canSkip("brain")).toBe(false);
    expect(canSkip("names")).toBe(false);
    expect(canSkip("vault")).toBe(true);
    expect(canSkip("phone")).toBe(true);
  });
});

import { modelRows, visibleThread } from "./setup";

describe("setup screen", () => {
  it("hides Odie's own notes but not the user's words in brackets", () => {
    const shown = visibleThread([
      { role: "user", text: "(The Tavily key was saved.)", note: true },
      { role: "user", text: "(just kidding)" },
      { role: "assistant", text: "Hi" },
    ]);
    expect(shown.map((m) => m.text)).toEqual(["(just kidding)", "Hi"]);
  });

  it("lists models per provider, local first, and filters by a search", () => {
    const providers = [
      { id: "openrouter", name: "OpenRouter", local: false, error: null, models: Array.from({ length: 300 }, (_, i) => ({ id: `vendor/model-${i}`, local: false })) },
      { id: "lmstudio", name: "LM Studio", local: true, error: null, models: [{ id: "gemma-4-12b", local: true }] },
    ];
    const rows = modelRows(providers, "", 8);
    expect(rows[0].m.id).toBe("gemma-4-12b");
    expect(rows.filter((r) => r.p.id === "openrouter").length).toBe(8);
    expect(modelRows(providers, "model-299", 8).map((r) => r.m.id)).toEqual(["vendor/model-299"]);
  });

  it("knows what a choice needs before it's saved", () => {
    const key = { type: "key" as const, provider: "openai", kind: "provider" as const, label: "OpenAI", note: "" };
    expect(formFor({ id: "openai", label: "OpenAI", note: "", recommended: false, needs: key })).toBe("key");
    expect(formFor({ id: "zapier", label: "Zapier", note: "", recommended: true, needs: { type: "app", app: "zapier", label: "Zapier", where: "", key_label: "" } })).toBe("app");
    expect(formFor({ id: "elsewhere", label: "Another folder", note: "", recommended: false, needs: { type: "path" } })).toBe("path");
    const server = { type: "server" as const, kinds: [{ id: "ollama", label: "Ollama", example: "http://studio.local:11434" }] };
    expect(formFor({ id: "elsewhere", label: "A server somewhere else", note: "", recommended: false, needs: server })).toBe("server");
    expect(formFor({ id: "kokoro", label: "Kokoro", note: "", recommended: true, needs: null })).toBeNull();
    expect(formFor(undefined)).toBeNull();
  });

  it("opens each step on the recommended choice", () => {
    const p = (choices: Panel["choices"]): Panel => ({ step: "voice", label: "Voice", question: "", explain: "", choices, skip: "Skip", fields: [], phone: null });
    const c = (id: string, recommended = false) => ({ id, label: id, note: "", recommended, needs: null });
    expect(firstPick(p([c("a"), c("b", true)]))).toBe("b");
    expect(firstPick(p([c("a"), c("b")]))).toBe("a");
    expect(firstPick(p([]))).toBe("");
  });
});
