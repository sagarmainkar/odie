import { describe, expect, it } from "vitest";
import type { Approval } from "./components/ApprovalCard";
import type { HistoryStep, Tool } from "./steps";
import { foldTurns, turnSoFar, withTurnEvent, type HistoryItem } from "./turns";

const step = (id: string, name = "run_shell"): HistoryStep => ({ name, id, args: {}, result: "", allowed: null, state: "done" });
const odie = (inv: string, text: string, more: Partial<HistoryItem> = {}): HistoryItem => ({ role: "odie", inv, text, tools: [], steps: [], ...more });
const user = (inv: string, text: string): HistoryItem => ({ role: "user", inv, text, tools: [] });
const card = (id: number, status: string, callId: string | null): HistoryItem => ({
  role: "approval", text: "", tools: [], ts: 100 + id,
  approval: { id, tool: "run_shell", summary: "Run ls", status, call_id: callId } satisfies Approval,
});

describe("foldTurns", () => {
  it("folds three Odie lines of one turn into one: texts joined by a blank line, steps and tools in order", () => {
    const items = [
      user("A", "Tidy my Downloads"),
      odie("A", "Sure.", { ts: 10, key: "k1", tools: ["now"], steps: [step("c1", "now")] }),
      odie("A", "", { ts: 11, tools: ["run_shell"], steps: [step("c2")] }),
      odie("A", "Done: two files moved.", { ts: 12, key: "k3", tools: [], steps: [] }),
    ];
    const got = foldTurns(items);
    expect(got).toHaveLength(2);
    expect(got[0]).toBe(items[0]);
    expect(got[1]).toMatchObject({ role: "odie", inv: "A", text: "Sure.\n\nDone: two files moved.", tools: ["now", "run_shell"] });
    expect(got[1].steps?.map((s) => s.id)).toEqual(["c1", "c2"]);
  });

  it("keeps the FIRST line's time and the LAST line's key (ticks hang off it), with its session", () => {
    const got = foldTurns([
      odie("A", "Sure.", { ts: 10, key: "k1", sid: "chat-1" }),
      odie("A", "Here's your list.", { ts: 50, key: "k2", sid: "chat-1" }),
      odie("A", "", { ts: 60, tools: ["now"], steps: [step("c3", "now")] }),  // no key: the last key stays k2
    ]);
    expect(got).toHaveLength(1);
    expect(got[0]).toMatchObject({ ts: 10, key: "k2", sid: "chat-1" });
  });

  it("takes media from every line, and private and usage from the last", () => {
    const memo = { id: "m1" } as NonNullable<HistoryItem["media"]>[number];
    const page = { id: "m2" } as NonNullable<HistoryItem["media"]>[number];
    const got = foldTurns([
      odie("A", "One.", { media: [memo], usage: { input: 1, cached: 0, output: 1 } }),
      odie("A", "Two.", { media: [page], private: true, usage: { input: 9, cached: 0, output: 9 } }),
    ]);
    expect(got[0].media).toEqual([memo, page]);
    expect(got[0]).toMatchObject({ private: true, usage: { input: 9, cached: 0, output: 9 } });
  });

  it("stays private when only an earlier line read a signed-in page", () => {
    const got = foldTurns([odie("A", "One.", { private: true }), odie("A", "Two.")]);
    expect(got[0].private).toBe(true);
  });

  it("never joins a line onto one holding blocks: its saved ticks keep their key and fence number", () => {
    const fenced = odie("A", "Packing list\n```odie-blocks\n[{\"type\": \"checklist\"}]\n```", { key: "k1" });
    const items = [fenced, odie("A", "Added a reminder.", { key: "k2" })];
    expect(foldTurns(items)).toEqual(items);
  });

  it("never joins onto a line whose blocks only become a fence as the chat draws it (a stray or one-line fence)", () => {
    const stray = odie("A", "```odie-checklist\n{\"items\": [\"Jacket\"]}\n```", { key: "k1" });
    const strayItems = [stray, odie("A", "Added a reminder.", { key: "k2" })];
    expect(foldTurns(strayItems)).toEqual(strayItems);
    const oneLine = odie("A", "Packing list ```odie-blocks: [{\"type\": \"checklist\", \"items\": [\"Jacket\"]}] ```", { key: "k1" });
    const oneLineItems = [oneLine, odie("A", "Added a reminder.", { key: "k2" })];
    expect(foldTurns(oneLineItems)).toEqual(oneLineItems);
  });

  it("keeps the first line's usage when the last line has none", () => {
    const got = foldTurns([odie("A", "One.", { usage: { input: 3, cached: 0, output: 2 } }), odie("A", "", { steps: [step("c2")] })]);
    expect(got).toHaveLength(1);
    expect(got[0].usage).toEqual({ input: 3, cached: 0, output: 2 });
  });

  it("still folds when the blocks are in the LAST line, whose key is kept", () => {
    const list = "Here's the list\n```odie-blocks\n[{\"type\": \"checklist\"}]\n```";
    const got = foldTurns([odie("A", "Sure.", { key: "k1" }), odie("A", list, { key: "k2" })]);
    expect(got).toHaveLength(1);
    expect(got[0]).toMatchObject({ text: `Sure.\n\n${list}`, key: "k2" });
  });

  it("never folds across a pending card: the card keeps its buttons in place (focus 1)", () => {
    const items = [odie("A", "I'll remove it.", { steps: [step("c1")] }), card(1, "pending", "c1"), odie("A", "Removed.")];
    expect(foldTurns(items)).toEqual(items);
  });

  it("folds across a decided card, and drops the card its step's pill already tells (focus 2)", () => {
    const got = foldTurns([odie("A", "I'll remove it.", { steps: [step("c1")] }), card(1, "approved", "c1"), odie("A", "Removed.")]);
    expect(got).toHaveLength(1);
    expect(got[0].text).toBe("I'll remove it.\n\nRemoved.");
  });

  it("keeps a decided card whose call no step on the line beside it has (focus 2)", () => {
    const got = foldTurns([odie("A", "Asking.", { steps: [step("c1")] }), card(2, "rejected", "c9"), odie("A", "Left it.")]);
    expect(got.map((m) => m.role)).toEqual(["odie", "approval"]);
    expect(got[1].approval?.id).toBe(2);
  });

  it("keeps a decided card with no call id (an old row)", () => {
    const got = foldTurns([odie("A", "Asking.", { steps: [step("c1")] }), card(3, "expired", null)]);
    expect(got.map((m) => m.role)).toEqual(["odie", "approval"]);
  });

  it("drops a decided card that sits right after or right before a line holding its step, even a line of its own", () => {
    expect(foldTurns([odie("A", "", { steps: [step("c1")] }), card(1, "approved", "c1")]).map((m) => m.role)).toEqual(["odie"]);
    expect(foldTurns([card(1, "rejected", "c1"), odie("A", "", { steps: [step("c1")] })]).map((m) => m.role)).toEqual(["odie"]);
  });

  it("keeps a decided card that isn't beside the line with its step", () => {
    const items = [odie("A", "", { steps: [step("c1")] }), user("B", "Thanks"), card(1, "approved", "c1")];
    expect(foldTurns(items)).toEqual(items);
  });

  it("leaves lines of different turns, lines with no turn, and a user line between alone", () => {
    const items = [odie("A", "One."), odie("B", "Two."), odie("", "Three."), odie("", "Four."), user("C", "Hi"), odie("C", "Hello."), user("C", "And?"), odie("C", "Then.")];
    expect(foldTurns(items)).toEqual(items);
  });
});

type M = { id: number; role: "user" | "odie" | "approval"; inv?: string; text: string; tools: Tool[]; private?: boolean };

describe("withTurnEvent", () => {
  const reply = (inv: string, text: string, tools: Tool[] = []): M => ({ id: 2, role: "odie", inv, text, tools });
  const asked: M = { id: 1, role: "user", inv: "A", text: "Remove old.txt", tools: [] };

  it("adds a starting step to the message of its turn", () => {
    const msgs = [asked, reply("A", "I'll remove it.")];
    const got = withTurnEvent(msgs, { type: "step_start", inv: "A", id: "c2", tool: "now", args: {}, gated: false });
    expect(got?.[1].tools).toEqual([{ name: "now", id: "c2", args: {}, gated: false, done: false }]);
    expect(got?.[0]).toBe(asked);
  });

  it("doesn't add a step the message already has (a reload got there first)", () => {
    const msgs = [reply("A", "", [{ name: "now", id: "c2", done: true }])];
    expect(withTurnEvent(msgs, { type: "step_start", inv: "A", id: "c2", tool: "now", args: {}, gated: false })).toBe(msgs);
  });

  it("marks a step waiting for a tap", () => {
    const msgs = [reply("A", "", [{ name: "run_shell", id: "c3", done: false }])];
    const got = withTurnEvent(msgs, { type: "step_wait", inv: "A", id: "c3", tool: "run_shell" });
    expect(got?.[0].tools[0]).toMatchObject({ state: "wait", done: false });
  });

  it("returns null for a wait or an answer whose step the turn's message doesn't hold (the caller falls back)", () => {
    const msgs = [reply("A", "", [{ name: "run_shell", id: "c3", done: false }])];
    expect(withTurnEvent(msgs, { type: "step_wait", inv: "A", id: "c9", tool: "run_shell" })).toBeNull();
    expect(withTurnEvent(msgs, { type: "step", inv: "A", id: "c9", tool: "run_shell", result: "ok" })).toBeNull();
  });

  it("doesn't add the words twice when the reload after the tap already brought them", () => {
    const msgs = [reply("A", "I'll remove it.\n\nRemoved old.txt.")];
    expect(withTurnEvent(msgs, { type: "message", inv: "A", text: "Removed old.txt." })).toBe(msgs);
  });

  it("returns null for words when the message or the words hold blocks: their ticks need a key of their own", () => {
    const list = "Packing list\n```odie-blocks\n[{\"type\": \"checklist\"}]\n```";
    const stray = "```odie-checklist\n{\"items\": [\"Jacket\"]}\n```";
    expect(withTurnEvent([reply("A", list)], { type: "message", inv: "A", text: "Added a reminder." })).toBeNull();
    expect(withTurnEvent([reply("A", stray)], { type: "message", inv: "A", text: "Added a reminder." })).toBeNull();
    expect(withTurnEvent([reply("A", "Sure.")], { type: "message", inv: "A", text: list })).toBeNull();
  });

  it("still skips words with blocks that the reload after the tap already folded in", () => {
    const list = "Here's the list\n```odie-blocks\n[{\"type\": \"checklist\"}]\n```";
    const msgs = [reply("A", `Sure.\n\n${list}`)];
    expect(withTurnEvent(msgs, { type: "message", inv: "A", text: list })).toBe(msgs);
  });

  it("fills a tapped step with its answer", () => {
    const msgs = [reply("A", "", [{ name: "run_shell", id: "c1", done: false, state: "wait" }])];
    const got = withTurnEvent(msgs, { type: "step", inv: "A", id: "c1", tool: "run_shell", result: "removed", allowed: { by: "you" } });
    expect(got?.[0].tools[0]).toMatchObject({ done: true, state: "done", result: "removed", allowed: { by: "you" } });
  });

  it("appends the words as a new paragraph, and marks it private when the words came from a signed-in page", () => {
    const msgs = [asked, reply("A", "I'll remove it.")];
    const got = withTurnEvent(msgs, { type: "message", inv: "A", text: "Removed old.txt.", private: true });
    expect(got?.[1]).toMatchObject({ id: 2, text: "I'll remove it.\n\nRemoved old.txt.", private: true });
  });

  it("puts the words in alone when the message had none yet", () => {
    const got = withTurnEvent([reply("A", "")], { type: "message", inv: "A", text: "Removed." });
    expect(got?.[0].text).toBe("Removed.");
  });

  it("changes only the last Odie message of that turn, never the user's line of it", () => {
    const first = reply("A", "One.");
    const last = { ...reply("A", "Two."), id: 3 };
    const got = withTurnEvent([asked, first, last], { type: "message", inv: "A", text: "Three." });
    expect(got?.[1]).toBe(first);
    expect(got?.[2].text).toBe("Two.\n\nThree.");
  });

  it("returns null when no message holds that turn, or the event has none: the caller falls back (focus 4)", () => {
    const msgs = [asked, reply("A", "One.")];
    expect(withTurnEvent(msgs, { type: "message", inv: "Z", text: "Hi." })).toBeNull();
    expect(withTurnEvent(msgs, { type: "step", inv: "Z", id: "c1", tool: "run_shell", result: "" })).toBeNull();
    expect(withTurnEvent(msgs, { type: "step_start", inv: "", id: "c1", tool: "now", args: {}, gated: false })).toBeNull();
    expect(withTurnEvent([], { type: "step_wait", inv: "A", id: "c1", tool: "now" })).toBeNull();
  });
});

describe("turnSoFar (the streaming message's turn)", () => {
  it("takes the turn from the first stream item that has a non-empty one, and keeps it", () => {
    const items = [{ type: "token", inv: "" }, { type: "tool_start" }, { type: "token", inv: "A" }, { type: "text", inv: "B" }];
    let turn = "";
    const seen: string[] = [];
    for (const item of items) { turn = turnSoFar(turn, item); seen.push(turn); }
    expect(seen).toEqual(["", "", "A", "A"]);
  });
  it("ignores an inv that isn't a string", () => {
    expect(turnSoFar("", { type: "token", inv: 7 })).toBe("");
  });
});
