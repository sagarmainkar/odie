import { describe, expect, it } from "vitest";
import { inUse, lastNote, searchSub, type SearchInfo } from "./search";

const rows = (on: string[]) => ["tavily", "brave", "ollama"].map((id) => ({ id, name: id, connected: on.includes(id), source: on.includes(id) ? ("settings" as const) : null, key_page: "" }));

describe("web search settings", () => {
  it("the one in use is the last that answered, else the first with a key, else free", () => {
    expect(inUse({ providers: rows(["brave"]), next: "brave" })).toBe("brave");
    expect(inUse({ providers: rows(["tavily", "brave"]), next: "tavily", last: { provider: "brave", failed: ["Tavily quota used up (432)"], at: "" } })).toBe("brave");
    expect(inUse({ providers: rows([]), next: "free" })).toBe("free");
    expect(inUse({ providers: rows(["ollama"]), next: "ollama", last: { provider: "brave", failed: [], at: "" } })).toBe("ollama");  // brave's key was removed since
  });
  it("says where a key comes from", () => {
    expect(searchSub({ id: "ollama", name: "Ollama", connected: true, source: "env", key_page: "" })).toBe("Key set in the environment");
    expect(searchSub({ id: "brave", name: "Brave", connected: false, source: null, key_page: "" })).toBe("Add a key to use it");
  });
  it("explains a hand-over only when something failed", () => {
    const d: SearchInfo = { providers: rows(["tavily"]), next: "tavily", last: { provider: "free", failed: ["Tavily key was refused (401)"], at: "" } };
    expect(lastNote(d)).toBe("Last search: Tavily key was refused (401) → the free fallback answered");
    expect(lastNote({ ...d, last: { provider: "tavily", failed: [], at: "" } })).toBe("");
  });
});
