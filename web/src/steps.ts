// What the chat remembers about each step (tool call) Odie takes: its arguments, its result, and who let it run.
// The pure functions here change a list of steps; Chat.tsx only calls them.
import { userLocale } from "./locale";

/** Who let a step run: "you" tapped Allow, "no" tapped Don't, "pass" ran under a pass (no card), "lapsed": nobody
 * tapped the card in time. `at` is the tap (or lapse) time. */
export type Allowed = { by: "you" | "no" | "pass" | "lapsed"; at?: string };

/** What became of a step: "done" it ran, "wait" it needs your tap, "no" it never ran (you refused it, or its card
 * lapsed), "lost" its answer never came (Odie restarted while it ran). */
export type StepState = "done" | "wait" | "no" | "lost";

/** One step. `done` is what the trace ticks; `state` is the receipt's word for it; `made`: it made a file for the
 * chat (the file's own card shows it). Old history only knows the name, so every field after `done` may be missing. */
export type Tool = {
  name: string; done: boolean;
  id?: string; args?: Record<string, unknown>; result?: string;
  allowed?: Allowed; state?: StepState; gated?: boolean; made?: boolean;
};

export type StartEvent = { tool: string; id?: string; args?: Record<string, unknown>; gated?: boolean };
export type WaitEvent = { tool: string; id?: string };
export type DoneEvent = { tool: string; id?: string; result?: string; allowed?: Allowed; made?: boolean };
export type StepEvent = { id: string; tool: string; result: string; allowed?: Allowed };

/** A step the server sent in history (`steps` on a reply): the same as Tool, with the answer already written in. */
export type HistoryStep = { name: string; id: string; args: Record<string, unknown>; result: string; allowed: Allowed | null; state: StepState; made?: boolean };
export type HistoryItem = { tools: string[]; steps?: HistoryStep[] };

/** A call begins: add it, not done yet.
 *    [] + {tool: "run_shell", id: "c1", args: {command: "ls"}, gated: true}
 *      -> [{name: "run_shell", id: "c1", args: {command: "ls"}, gated: true, done: false}] */
export function toolStarted(tools: Tool[], ev: StartEvent): Tool[] {
  return [...tools, { name: ev.tool, done: false, id: ev.id, args: ev.args, gated: ev.gated }];
}

/** Which step an event is about: the one with its id; with no id, the first step of that name still running.
 *    steps [web_search c1, web_search c2], event id c2           -> index 1
 *    steps [now done, now running], event "now" with no id       -> index 1
 *    event id c9, nobody has it                                  -> -1 (the caller changes nothing) */
function indexOfStep(tools: Tool[], ev: { tool: string; id?: string }): number {
  if (ev.id) return tools.findIndex((t) => t.id === ev.id);
  return tools.findIndex((t) => t.name === ev.tool && !t.done);
}

function withStep(tools: Tool[], at: number, change: Partial<Tool>): Tool[] {
  const next = [...tools];
  next[at] = { ...next[at], ...change };
  return next;
}

/** A gated call is waiting for your tap: mark it "wait". It is not done, and it stays so until the answer comes.
 *    [run_shell c1 running] + wait for c1 -> [run_shell c1, state "wait", done false]
 *    wait for an id nobody has            -> the list as it was */
export function toolWaiting(tools: Tool[], ev: WaitEvent): Tool[] {
  const at = indexOfStep(tools, ev);
  if (at < 0) return tools;
  return withStep(tools, at, { state: "wait", done: false });
}

/** A call finished: tick it and keep its result, who allowed it, and whether it made a file. A rejection
 * (allowed.by "no") is state "no". It keeps the allowed it already had when the event carries none.
 *    run_shell c1 + done {result: "a.txt", allowed: {by: "pass"}} -> done, state "done", result "a.txt"
 *    run_shell c1 + done {result: "", allowed: {by: "no"}}        -> done, state "no", result ""
 *    run_shell c1 (allowed pass) + done {result: "ok"}            -> done, still allowed pass
 *    speak c3 + done {result: "...", made: true}                  -> done, made true
 *    web_search c2 of two web_search steps                        -> only c2 changes */
export function toolDone(tools: Tool[], ev: DoneEvent): Tool[] {
  const at = indexOfStep(tools, ev);
  if (at < 0) return tools;
  const allowed = ev.allowed ?? tools[at].allowed;
  const state = allowed?.by === "no" ? "no" : "done";
  return withStep(tools, at, { done: true, state, result: ev.result, allowed, made: ev.made });
}

/** The answer to a step you tapped on (the bus `step` event, which can arrive after the stream ended): it finds the
 * step by id only, because a wait step has no other safe match. It keeps the allowed it already had when the event
 * carries none.
 *    [run_shell c1, wait] + {id: c1, result: "removed", allowed: {by: "you"}} -> done, "removed", allowed you
 *    [run_shell c1, wait] + {id: c1, result: "", allowed: {by: "no"}}         -> state "no" (Not run)
 *    an id no step has, or an event with no id                                -> the list as it was */
export function stepFilled(tools: Tool[], ev: StepEvent): Tool[] {
  if (!ev.id) return tools;  // an id-less step would match an id-less (old) step by accident
  const at = tools.findIndex((t) => t.id === ev.id);
  if (at < 0) return tools;
  const allowed = ev.allowed ?? tools[at].allowed;
  const state = allowed?.by === "no" ? "no" : "done";
  return withStep(tools, at, { done: true, state, result: ev.result, allowed });
}

/** The bus `step` event across the whole chat: fill the step on the last message that holds its id (the newest reply
 * with that call), and leave every other message as it was.
 *    [reply 1 with c1 waiting] + step c1 "removed"           -> reply 1's c1 done, "removed"
 *    [reply 1 with c1, reply 2 with c1] + step c1            -> only reply 2 changes
 *    no message holds the id, or the event has no id        -> the same list (nothing re-renders) */
export function withStepEvent<M extends { tools: Tool[] }>(msgs: M[], ev: StepEvent): M[] {
  if (!ev.id) return msgs;
  const at = msgs.findLastIndex((m) => m.tools.some((t) => t.id === ev.id));
  if (at < 0) return msgs;
  const next = [...msgs];
  next[at] = { ...msgs[at], tools: stepFilled(msgs[at].tools, ev) };
  return next;
}

/** The reply ended (done, error, or an approval card took over): tick every step still running, except one waiting
 * for your tap, which stays waiting until the answer comes.
 *    [now running, run_shell waiting for a tap] -> [now ticked, run_shell still waiting]
 *    [recall done]                              -> [recall done] (unchanged) */
export function settled(tools: Tool[]): Tool[] {
  return tools.map((t) => (t.state === "wait" ? t : { ...t, done: true }));
}

/** A reply's steps from history: the full `steps` when the server sent them (a "wait" step is not done), else just
 * the names as finished steps, as old history had.
 *    {tools: ["now"], steps: [{name: "run_shell", id: "c2", state: "wait", ...}]} -> [run_shell c2, done false, state "wait"]
 *    {tools: ["now", "recall"]}                                                    -> [now done, recall done] */
export function fromHistory(item: HistoryItem): Tool[] {
  if (item.steps?.length) {
    return item.steps.map((s) => ({
      name: s.name, id: s.id, args: s.args, result: s.result, state: s.state,
      allowed: s.allowed ?? undefined, done: s.state !== "wait", made: s.made,
    }));
  }
  return item.tools.map((name) => ({ name, done: true }));
}

/** The small pill on the right of a step that says who let it run, in words (the time in this device's own clock).
 *    allowed {by: "you", at: 10:42}             -> You allowed · 10:42 (also when it never ran: the resume failed)
 *    allowed {by: "you"} (no time known)        -> You allowed
 *    allowed {by: "lapsed"}                     -> Lapsed  (nobody tapped the card in time)
 *    allowed {by: "no"}, or state "no" alone    -> You said no
 *    allowed {by: "pass"}                       -> pass   (a shell command under the pass: no card)
 *    no allowed (no tap was needed)             -> ""     (no pill) */
export function allowedPill(t: Tool): string {
  const by = t.allowed?.by;
  if (by === "you") {
    const time = tapTime(t.allowed?.at);
    if (!time) return "You allowed";
    return `You allowed · ${time}`;
  }
  if (by === "lapsed") return "Lapsed";
  if (by === "no" || t.state === "no") return "You said no";
  if (by === "pass") return "pass";
  return "";
}

/** A tap's time as the owner reads a clock: 12:01. Empty when there is no time or it can't be read.
 *    2026-11-05T12:01:00Z read in UTC -> 12:01     undefined -> "" */
export function tapTime(at: string | undefined | null): string {
  if (!at) return "";
  const when = new Date(at);
  if (Number.isNaN(when.getTime())) return "";
  return when.toLocaleTimeString(userLocale(), { hour: "2-digit", minute: "2-digit", hour12: false });
}

function cut(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

function valueText(value: unknown): string {
  return typeof value === "string" ? cut(value, 80) : JSON.stringify(value);
}

/** The one line that says what a step was asked, by the argument people care about. Other tools list their arguments.
 *    run_shell {command: "ls ~/Downloads"}      -> ls ~/Downloads
 *    web_search {query: "cats"}                 -> "cats"   (with the quotes)
 *    web_fetch {url: "https://a.test"}          -> https://a.test
 *    task_add {title: "Call the dentist", due: "Fri"} -> title: Call the dentist · due: Fri   (strings cut at 80 characters)
 *    now {}                                     -> ""
 *    run_shell {cwd: "/tmp"} (no command)       -> cwd: /tmp */
export function argLine(t: Tool): string {
  const args = t.args ?? {};
  const one = (key: string) => (typeof args[key] === "string" ? (args[key] as string) : undefined);
  const command = one("command");
  const query = one("query");
  const url = one("url");
  const note = one("note");
  const title = one("title");
  if (t.name === "run_shell" && command !== undefined) return command;
  if (["web_search", "recall", "search_everything", "find_images"].includes(t.name) && query !== undefined) return `"${query}"`;
  if (["web_fetch", "browser_open"].includes(t.name) && url !== undefined) return url;
  if (t.name === "read_note" && note !== undefined) return note;
  if (t.name === "fetch_memory" && title !== undefined) return title;
  return Object.entries(args).map(([key, value]) => `${key}: ${valueText(value)}`).join(" · ");
}

function linesOf(result: string): string[] {
  const body = result.replace(/\n+$/, "");
  return body ? body.split("\n") : [];
}

/** The small grey line under a step's name.
 *    state "wait"                          -> Waiting for your tap
 *    state "no"                            -> Not run
 *    state "lost"                          -> No result   (its answer never came)
 *    made a file                           -> Made a file (the file's card shows it)
 *    result ""                             -> No output
 *    result "a\nb\nc\n"                    -> 3 lines · tap to see them
 *    no result at all (old history, or still running) -> "" (nothing to say) */
export function metaLine(t: Tool): string {
  if (t.state === "wait") return "Waiting for your tap";
  if (t.state === "no") return "Not run";
  if (t.state === "lost") return "No result";
  if (t.made) return "Made a file";
  if (t.result === undefined) return "";
  const count = linesOf(t.result).length;
  if (count === 0) return "No output";
  return `${count} ${count === 1 ? "line" : "lines"} · tap to see them`;
}

/** The first lines of a result and how many lines are left unseen.
 *    20 lines, lines = 12   -> {head: first 12 joined by newlines, rest: 8}
 *    "a\nb\n", lines = 12   -> {head: "a\nb", rest: 0}
 *    ""                     -> {head: "", rest: 0} */
export function outputHead(result: string, lines = 12): { head: string; rest: number } {
  const all = linesOf(result);
  return { head: all.slice(0, lines).join("\n"), rest: Math.max(0, all.length - lines) };
}
