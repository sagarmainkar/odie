import { describe, expect, it } from "vitest";
import { toChats, toolDetail } from "./chats";

const score = { fences: 0, parsed: true, kinds: [], dropped: [], not_drawn: [] };
const turn = { n: 1, user: "Hi", reply: "Hello", tools: [], visuals: false, media: [], error: null, seconds: 1, tokens: { input: 1, output: 1 }, score };
const chat = (model: string, source: "live" | "replay", provider = "anthropic") =>
  ({ source, provider, model, date: "2026-10-11", turns: [turn], totals: { seconds: 1, input: 1, output: 1, errors: 0 } });

describe("toChats", () => {
  it("puts the live chat first, then replays by model", () => {
    const files = { "a.json": chat("claude-sonnet-5-5", "replay"), "b.json": chat("claude-opus-5-5", "replay"), "c.json": chat("gemma-4-26b-a4b-it-qat", "live", "lmstudio") };
    expect(toChats(files).map((c) => c.model)).toEqual(["gemma-4-26b-a4b-it-qat", "claude-opus-5-5", "claude-sonnet-5-5"]);
  });
  it("leaves out a turn list, an unscored chat and anything else", () => {
    const unscored = { ...chat("x", "replay"), turns: [{ ...turn, score: undefined }].map(({ score: _, ...t }) => t) };
    expect(toChats({ "t.turns.json": { id: "t", turns: ["Hi"] }, "u.json": unscored, "n.json": null })).toEqual([]);
  });
});

describe("toolDetail", () => {
  it("picks the argument that says most, or the podcast hosts", () => {
    expect(toolDetail({ tool: "web_search", args: { query: "Pixel 10a price" } })).toBe("Pixel 10a price");
    expect(toolDetail({ tool: "load_skill", args: { skill_name: "visuals" } })).toBe("visuals");
    expect(toolDetail({ tool: "speak", args: { script: "…" }, hosts: ["Asha", "Rohan"] })).toBe("Asha & Rohan");
    expect(toolDetail({ tool: "odie_features", args: {} })).toBe("");
    expect(toolDetail({ tool: "web_search", args: { query: "x".repeat(60) } })).toBe("x".repeat(40) + "…");
  });
});
