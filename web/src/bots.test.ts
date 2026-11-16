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
    expect(madeWords(bot({ made_by: "odie" }))).toBe("starter");
  });
});

import { botFromHash, botHref, matches, rowLine, sortBots, whenWords } from "./bots";
import { creatureSvg, mix, safeLook } from "./creature";
import { tabFromHash } from "./App";

describe("the bots list", () => {
  const b = (over: Partial<Bot>): Bot => bot({ ...over });
  it("puts the chief first, then who needs you, then the latest", () => {
    const list = sortBots([b({ name: "old", updated_at: "2026-11-10T00:00:00Z" }), b({ name: "new", updated_at: "2026-11-15T00:00:00Z" }),
      b({ name: "asks", needs_you: true }), b({ name: "chief", chief: true })]);
    expect(list.map((x) => x.name)).toEqual(["chief", "asks", "new", "old"]);
  });
  it("shows the question, the live step, the last message or a hello", () => {
    expect(rowLine(b({ needs_you: true, ask: "Add to cart?" }))).toBe("Add to cart?");
    expect(rowLine(b({ working: true, live: "reading zigwheels.com" }))).toBe("reading zigwheels.com…");
    expect(rowLine(b({ preview: "Done." }))).toBe("Done.");
    expect(rowLine(b({ role: "Finds sources" }))).toBe("I'm researcher: finds sources");
  });
  it("names times like a messaging app", () => {
    const now = new Date("2026-11-15T15:00:00");
    expect(whenWords(null, now)).toBe("");
    expect(whenWords("2026-11-14T10:00:00", now)).toBe("Yesterday");
    expect(whenWords("2026-11-12T10:00:00", now, "en-GB")).toBe("12 Nov");
  });
  it("searches names, roles and last lines", () => {
    expect(matches(b({ preview: "Goa tides" }), "tides")).toBe(true);
    expect(matches(b({}), "zzz")).toBe(false);
    expect(matches(b({}), " ")).toBe(true);
  });
  it("reads and writes a bot's address", () => {
    expect(botHref({ name: "chief", conversation: "conv-1a2b" })).toBe("#bot/chief/conv-1a2b");
    expect(botHref({ name: "chief", conversation: null })).toBe("#bot/chief");
    expect(botFromHash("#bot/chief/conv-1a2b")).toEqual({ bot: "chief", conv: "conv-1a2b" });
    expect(botFromHash("#bot/chief")).toEqual({ bot: "chief", conv: null });
    expect(botFromHash("#bot/Chief/<x>")).toBeNull();
    expect(botFromHash("#bot/chief/new")).toEqual({ bot: "chief", conv: "new" });
    expect(tabFromHash("#bot/chief/conv-1a2b")).toBe("bot");
    expect(tabFromHash("#bots")).toBe("bots");
    expect(tabFromHash("#nowhere")).toBe("today");
  });
});

describe("creatures", () => {
  it("draws only from its own tables", () => {
    expect(safeLook({ shape: "hex", color: "#8B6CF6", eyes: "round" })).toEqual({ shape: "hex", color: "#8B6CF6", eyes: "round" });
    expect(safeLook({ shape: "<script>", color: "red", eyes: "x" })).toEqual({ shape: "squircle", color: "#7C8AA5", eyes: "round" });
    expect(creatureSvg({ shape: "hex", color: "#8B6CF6\"/><script>", eyes: "round" })).not.toContain("<script>");
    expect(mix("#000000", "#ffffff", 0.5)).toBe("#808080");
  });
});

import { activityLine, nextWords, routineState } from "./bots";

describe("routines and recent work", () => {
  it("says when a routine runs next", () => {
    const now = new Date("2026-11-16T07:00:00");
    expect(nextWords(null, now)).toBe("paused");
    expect(nextWords("2026-11-16T08:30:00", now, "en-GB")).toBe("today 8:30");
    expect(nextWords("2026-11-17T08:30:00", now, "en-GB")).toBe("tomorrow 8:30");
    expect(nextWords("2026-11-19T08:30:00", now, "en-GB")).toBe("Thu 8:30");
    expect(nextWords("2026-12-01T09:00:00", now, "en-GB")).toBe("1 Dec 9:00");
  });
  it("says a routine's state", () => {
    const now = new Date("2026-11-16T07:00:00");
    expect(routineState({ paused: true, finished: false, next_run_at: null }, now)).toBe("paused");
    expect(routineState({ paused: false, finished: true, next_run_at: null }, now)).toBe("finished");
    expect(routineState({ paused: false, finished: false, next_run_at: "2026-11-17T08:30:00" }, now, "en-GB")).toBe("next tomorrow 8:30");
  });
  it("says how a job went", () => {
    const a = { id: "j", title: "t", status: "done", outcome: "ready", started_at: null, ended_at: null, calls: 12, conv: null, for_chief: false, error: null };
    expect(activityLine(a)).toBe("done · 12 steps");
    expect(activityLine({ ...a, status: "failed", calls: 1 })).toBe("didn't finish · 1 step");
    expect(activityLine({ ...a, for_chief: true, outcome: "blocked" })).toBe("for chief · stuck · 12 steps");
  });
});
