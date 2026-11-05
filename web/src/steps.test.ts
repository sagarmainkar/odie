import { describe, expect, it } from "vitest";
import { allowedPill, argLine, fromHistory, metaLine, outputHead, settled, stepFilled, toolDone, toolStarted, toolWaiting, withStepEvent, type Tool } from "./steps";

const running = (name: string, id: string): Tool => ({ name, id, done: false, args: {} });

describe("toolStarted", () => {
  it("adds a running step that keeps its id, args and gated flag", () => {
    const got = toolStarted([], { tool: "run_shell", id: "c1", args: { command: "ls" }, gated: true });
    expect(got).toEqual([{ name: "run_shell", id: "c1", args: { command: "ls" }, gated: true, done: false }]);
  });
  it("works for an old event with no id or args", () => {
    expect(toolStarted([], { tool: "now" })).toEqual([{ name: "now", done: false, id: undefined, args: undefined, gated: undefined }]);
  });
});

describe("toolWaiting", () => {
  it("marks the step with that id as waiting for the tap, still not done", () => {
    const got = toolWaiting([running("run_shell", "c1")], { tool: "run_shell", id: "c1" });
    expect(got[0]).toMatchObject({ state: "wait", done: false });
  });
  it("ignores an id it does not know", () => {
    const tools = [running("run_shell", "c1")];
    expect(toolWaiting(tools, { tool: "run_shell", id: "zzz" })).toEqual(tools);
  });
});

describe("toolDone", () => {
  it("fills in result and allowed, and ticks the step", () => {
    const got = toolDone([running("run_shell", "c1")], { tool: "run_shell", id: "c1", result: "a.txt", allowed: { by: "pass" } });
    expect(got[0]).toMatchObject({ done: true, state: "done", result: "a.txt", allowed: { by: "pass" } });
  });
  it("matches by id when two steps share a name", () => {
    const tools = [running("web_search", "c1"), running("web_search", "c2")];
    const got = toolDone(tools, { tool: "web_search", id: "c2", result: "two" });
    expect(got[0].done).toBe(false);
    expect(got[1]).toMatchObject({ done: true, result: "two" });
  });
  it("falls back to the first undone step of that name when there is no id", () => {
    const tools: Tool[] = [{ name: "now", done: true }, { name: "now", done: false }, { name: "now", done: false }];
    const got = toolDone(tools, { tool: "now" });
    expect(got.map((t) => t.done)).toEqual([true, true, false]);
  });
  it("a rejection is state no, with an empty result", () => {
    const got = toolDone([running("run_shell", "c1")], { tool: "run_shell", id: "c1", result: "", allowed: { by: "no" } });
    expect(got[0]).toMatchObject({ done: true, state: "no", result: "" });
  });
  it("finishes a step that was waiting", () => {
    const waiting = toolWaiting([running("run_shell", "c1")], { tool: "run_shell", id: "c1" });
    expect(toolDone(waiting, { tool: "run_shell", id: "c1", result: "ok" })[0]).toMatchObject({ done: true, state: "done" });
  });
  it("changes nothing when no step matches", () => {
    const tools = [running("a", "c1")];
    expect(toolDone(tools, { tool: "b", id: "c9", result: "x" })).toEqual(tools);
  });
  it("keeps the allowed it had when the event carries none", () => {
    const had: Tool[] = [{ name: "run_shell", id: "c1", done: false, allowed: { by: "pass" } }];
    expect(toolDone(had, { tool: "run_shell", id: "c1", result: "ok" })[0].allowed).toEqual({ by: "pass" });
  });
  it("keeps that the step made a file", () => {
    const got = toolDone([running("speak", "c1")], { tool: "speak", id: "c1", result: "The memo is under your reply.", made: true });
    expect(got[0]).toMatchObject({ done: true, made: true });
    expect(toolDone([running("now", "c2")], { tool: "now", id: "c2", result: "9:31" })[0].made).toBeUndefined();
  });
});

describe("stepFilled", () => {
  const waiting: Tool[] = [{ name: "run_shell", id: "c1", done: false, state: "wait", args: { command: "rm x" } }];
  it("fills a waiting step after the tap", () => {
    const got = stepFilled(waiting, { id: "c1", tool: "run_shell", result: "removed", allowed: { by: "you", at: "2026-11-05T10:00:00" } });
    expect(got[0]).toMatchObject({ done: true, state: "done", result: "removed", allowed: { by: "you", at: "2026-11-05T10:00:00" }, args: { command: "rm x" } });
  });
  it("a no tap makes the step Not run", () => {
    const got = stepFilled(waiting, { id: "c1", tool: "run_shell", result: "", allowed: { by: "no" } });
    expect(got[0]).toMatchObject({ done: true, state: "no", result: "" });
  });
  it("keeps the allowed it had when the event carries none", () => {
    const had: Tool[] = [{ name: "run_shell", id: "c1", done: false, allowed: { by: "pass" } }];
    expect(stepFilled(had, { id: "c1", tool: "run_shell", result: "ok" })[0].allowed).toEqual({ by: "pass" });
  });
  it("ignores an unknown id", () => {
    expect(stepFilled(waiting, { id: "nope", tool: "run_shell", result: "x" })).toEqual(waiting);
  });
  it("ignores an event with no id, even when a step has none either", () => {
    const idless: Tool[] = [{ name: "now", done: false }];
    expect(stepFilled(idless, { id: "", tool: "now", result: "x" })).toEqual(idless);
    expect(stepFilled(idless, { tool: "now", result: "x" } as never)).toEqual(idless);
  });
});

describe("withStepEvent", () => {
  type M = { id: number; tools: Tool[] };
  const wait = (id: string): Tool => ({ name: "run_shell", id, done: false, state: "wait" });
  const event = { id: "c1", tool: "run_shell", result: "removed", allowed: { by: "you" as const } };
  it("fills the step on the message that holds its id", () => {
    const msgs: M[] = [{ id: 1, tools: [] }, { id: 2, tools: [wait("c1")] }];
    const got = withStepEvent(msgs, event);
    expect(got[1].tools[0]).toMatchObject({ done: true, result: "removed", allowed: { by: "you" } });
    expect(got[0]).toBe(msgs[0]);
  });
  it("fills only the last message that holds the id", () => {
    const msgs: M[] = [{ id: 1, tools: [wait("c1")] }, { id: 2, tools: [wait("c1")] }];
    const got = withStepEvent(msgs, event);
    expect(got[0]).toBe(msgs[0]);
    expect(got[1].tools[0].result).toBe("removed");
  });
  it("returns the same list when no message holds the id, or the event has none", () => {
    const msgs: M[] = [{ id: 1, tools: [wait("c1")] }, { id: 2, tools: [{ name: "now", done: false }] }];
    expect(withStepEvent(msgs, { ...event, id: "c9" })).toBe(msgs);
    expect(withStepEvent(msgs, { ...event, id: "" })).toBe(msgs);
  });
});

describe("settled", () => {
  it("ticks every running step when the reply ends, and leaves a step waiting for a tap as it is", () => {
    const tools: Tool[] = [
      { name: "now", id: "c1", done: false },
      { name: "run_shell", id: "c2", done: false, state: "wait" },
      { name: "recall", id: "c3", done: true, state: "done" },
    ];
    expect(settled(tools).map((t) => [t.name, t.done, t.state])).toEqual([["now", true, undefined], ["run_shell", false, "wait"], ["recall", true, "done"]]);
  });
});

describe("allowedPill", () => {
  const at = new Date(2026, 10, 5, 10, 42).toISOString();  // 10:42 in this computer's own time zone
  it("says who let it run", () => {
    expect(allowedPill({ name: "run_shell", done: true, allowed: { by: "you", at } })).toBe("You allowed · 10:42");
    expect(allowedPill({ name: "run_shell", done: true, allowed: { by: "you" } })).toBe("You allowed");
    expect(allowedPill({ name: "run_shell", done: true, allowed: { by: "pass" } })).toBe("pass");
    expect(allowedPill({ name: "run_shell", done: true, state: "no", allowed: { by: "no", at } })).toBe("You said no");
    expect(allowedPill({ name: "run_shell", done: true, state: "no" })).toBe("You said no");
  });
  it("says Lapsed for a card nobody tapped in time", () => {
    expect(allowedPill({ name: "run_shell", done: true, state: "no", allowed: { by: "lapsed", at } })).toBe("Lapsed");
  });
  it("keeps the tap on a step that was allowed but never ran (the resume failed)", () => {
    expect(allowedPill({ name: "run_shell", done: true, state: "no", allowed: { by: "you", at } })).toBe("You allowed · 10:42");
  });
  it("says nothing when no tap was needed", () => {
    expect(allowedPill({ name: "web_search", done: true })).toBe("");
    expect(allowedPill({ name: "run_shell", done: true, allowed: { by: "you", at: "not a time" } })).toBe("You allowed");
  });
});

describe("fromHistory", () => {
  it("uses steps when present", () => {
    const got = fromHistory({
      tools: ["run_shell", "web_search", "run_shell"],
      steps: [
        { name: "run_shell", id: "c1", args: { command: "ls" }, result: "a", allowed: { by: "pass" }, state: "done" },
        { name: "run_shell", id: "c2", args: { command: "rm a" }, result: "", allowed: null, state: "wait" },
        { name: "run_shell", id: "c3", args: { command: "rm b" }, result: "", allowed: { by: "no" }, state: "no" },
      ],
    });
    expect(got.map((t) => [t.id, t.state, t.done])).toEqual([["c1", "done", true], ["c2", "wait", false], ["c3", "no", true]]);
    const lost = fromHistory({ tools: ["run_shell"], steps: [{ name: "run_shell", id: "c4", args: {}, result: "", allowed: null, state: "lost" }] });
    expect(lost[0]).toMatchObject({ state: "lost", done: true });  // no answer will come: nothing to wait for
    const made = fromHistory({ tools: ["speak"], steps: [{ name: "speak", id: "c5", args: {}, result: "ok", allowed: null, state: "done", made: true }] });
    expect(made[0].made).toBe(true);
    expect(got[0]).toMatchObject({ args: { command: "ls" }, result: "a", allowed: { by: "pass" } });
    expect(got[1].allowed).toBeUndefined();
  });
  it("falls back to the names as finished steps", () => {
    expect(fromHistory({ tools: ["now", "recall"] })).toEqual([{ name: "now", done: true }, { name: "recall", done: true }]);
  });
  it("falls back to names when steps is empty", () => {
    expect(fromHistory({ tools: ["now"], steps: [] })).toEqual([{ name: "now", done: true }]);
  });
});

describe("argLine", () => {
  const t = (name: string, args?: Record<string, unknown>): Tool => ({ name, done: true, args });
  it("shows the command for run_shell", () => expect(argLine(t("run_shell", { command: "ls ~/Downloads" }))).toBe("ls ~/Downloads"));
  it("quotes the query for searches", () => {
    for (const n of ["web_search", "recall", "search_everything", "find_images"]) expect(argLine(t(n, { query: "cats" }))).toBe('"cats"');
  });
  it("shows the url for web_fetch and browser_open", () => {
    expect(argLine(t("web_fetch", { url: "https://a.test/x" }))).toBe("https://a.test/x");
    expect(argLine(t("browser_open", { url: "https://b.test" }))).toBe("https://b.test");
  });
  it("shows the note for read_note and the title for fetch_memory", () => {
    expect(argLine(t("read_note", { note: "Plans.md" }))).toBe("Plans.md");
    expect(argLine(t("fetch_memory", { title: "Dentist" }))).toBe("Dentist");
  });
  it("lists key: value pairs for any other tool, cutting long strings at 80", () => {
    expect(argLine(t("task_add", { title: "Call the dentist", due: "Fri", urgent: true }))).toBe("title: Call the dentist · due: Fri · urgent: true");
    const long = argLine(t("task_add", { title: "x".repeat(200) }));
    expect(long).toBe(`title: ${"x".repeat(80)}…`);
  });
  it("is empty for no args, and falls back to pairs when the usual key is missing", () => {
    expect(argLine(t("now"))).toBe("");
    expect(argLine(t("now", {}))).toBe("");
    expect(argLine(t("run_shell", { cwd: "/tmp" }))).toBe("cwd: /tmp");
  });
});

describe("metaLine", () => {
  it("says what a waiting or refused step is", () => {
    expect(metaLine({ name: "run_shell", done: false, state: "wait" })).toBe("Waiting for your tap");
    expect(metaLine({ name: "run_shell", done: true, state: "no", result: "" })).toBe("Not run");
  });
  it("says No result for a call whose answer never came", () => {
    expect(metaLine({ name: "run_shell", done: true, state: "lost", result: "" })).toBe("No result");
  });
  it("says Made a file for a step that made one", () => {
    expect(metaLine({ name: "speak", done: true, state: "done", result: "The memo is under your reply.", made: true })).toBe("Made a file");
  });
  it("says No output for an empty result", () => expect(metaLine({ name: "run_shell", done: true, result: "" })).toBe("No output"));
  it("counts the lines", () => {
    expect(metaLine({ name: "run_shell", done: true, result: "a\nb\nc\n" })).toBe("3 lines · tap to see them");
    expect(metaLine({ name: "run_shell", done: true, result: "a" })).toBe("1 line · tap to see them");
  });
  it("says nothing for a step with no receipt (old history, or still running)", () => {
    expect(metaLine({ name: "now", done: true })).toBe("");
  });
});

describe("outputHead", () => {
  it("returns the first 12 lines and how many are left", () => {
    const text = Array.from({ length: 20 }, (_, i) => `l${i + 1}`).join("\n");
    const got = outputHead(text);
    expect(got.head.split("\n")).toHaveLength(12);
    expect(got.head.endsWith("l12")).toBe(true);
    expect(got.rest).toBe(8);
  });
  it("keeps a short result whole", () => expect(outputHead("a\nb\n")).toEqual({ head: "a\nb", rest: 0 }));
  it("takes a different line count", () => expect(outputHead("a\nb\nc", 2)).toEqual({ head: "a\nb", rest: 1 }));
  it("handles empty", () => expect(outputHead("")).toEqual({ head: "", rest: 0 }));
});
