// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import { Steps, stepsSummary, toolLabel } from "./Steps";
import type { Tool } from "../steps";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe("steps", () => {
  it("labels by tense", () => {
    expect(toolLabel({ name: "gmail_search", done: false })).toBe("Searching mail");
    expect(toolLabel({ name: "gmail_search", done: true })).toBe("Searched mail");
    expect(toolLabel({ name: "mystery", done: true })).toBe("Used mystery");          // never a raw id
    expect(toolLabel({ name: "GMAIL_FETCH_EMAILS", done: false })).toBe("Using gmail fetch emails");
    expect(toolLabel({ name: "load_skill", done: true })).toBe("Loaded a skill");
    expect(toolLabel({ name: "find_clips", done: false })).toBe("Finding clips");
    expect(toolLabel({ name: "find_clips", done: true })).toBe("Found clips");
  });
  it("summarises unique steps", () => {
    expect(stepsSummary([{ name: "gmail_search", done: true }, { name: "gmail_search", done: true }, { name: "calendar_list_events", done: true }]))
      .toBe("Searched mail, checked calendar");
  });
});

const at = new Date(2026, 10, 5, 10, 42).toISOString();  // 10:42 in this computer's own time zone
const listing = Array.from({ length: 38 }, (_, i) => `file-${i + 1}.txt`).join("\n");
const receipt: Tool[] = [
  { name: "run_shell", id: "c1", done: true, state: "done", args: { command: "ls -la ~/Downloads" }, result: listing, allowed: { by: "pass" } },
  { name: "run_shell", id: "c2", done: true, state: "done", args: { command: "mkdir -p ~/Downloads/old" }, result: "", allowed: { by: "you", at } },
  { name: "web_search", id: "c3", done: true, state: "done", args: { query: "clear Downloads" }, result: "r1\nr2\nr3\nr4\nr5" },
  { name: "run_shell", id: "c4", done: true, state: "no", args: { command: "rm -rf ~/Downloads/old" }, result: "", allowed: { by: "no", at } },
];

let unmount: (() => void) | null = null;
afterEach(() => { unmount?.(); unmount = null; document.body.innerHTML = ""; });

async function openTrace(tools: Tool[], running = false) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => root.render(<Steps tools={tools} running={running} />));
  unmount = () => act(() => root.unmount());
  const header = host.querySelector<HTMLButtonElement>("button[aria-expanded]")!;
  if (header.getAttribute("aria-expanded") === "false") await act(async () => header.click());
  return host;
}

const stepsIn = (host: HTMLElement) => [...host.querySelectorAll<HTMLElement>("[data-step]")];
const buttonNamed = (el: HTMLElement, text: string) => [...el.querySelectorAll("button")].find((b) => b.textContent?.includes(text));
const argText = (step: HTMLElement) => step.querySelector<HTMLElement>("[data-arg] span")!;

describe("the opened receipt", () => {
  it("shows each step's argument line and who let it run", async () => {
    const host = await openTrace(receipt);
    const [pass, you, search, no] = stepsIn(host);
    expect(pass.textContent).toContain("ls -la ~/Downloads");
    expect(pass.textContent).toContain("pass");
    expect(you.textContent).toContain("mkdir -p ~/Downloads/old");
    expect(you.textContent).toContain("You allowed · 10:42");
    expect(search.textContent).toContain('"clear Downloads"');
    expect(search.textContent).not.toMatch(/You allowed|pass|You said no/);  // no tap was needed: no pill
    expect(no.textContent).toContain("You said no");
    expect(no.textContent).toContain("Not run");
  });

  it("sets a shell command in mono and a search in the body font", async () => {
    const host = await openTrace(receipt);
    const [pass, , search] = stepsIn(host);
    expect(argText(pass).className).toContain("font-mono");
    expect(argText(search).className).not.toContain("font-mono");
  });

  it("cuts the argument line to one line, and a tap shows it whole", async () => {
    const host = await openTrace(receipt);
    const arg = buttonNamed(stepsIn(host)[0], "ls -la")!;
    expect(argText(stepsIn(host)[0]).className).toContain("truncate");
    await act(async () => arg.click());
    expect(argText(stepsIn(host)[0]).className).not.toContain("truncate");
    expect(arg.getAttribute("aria-expanded")).toBe("true");
    expect(stepsIn(host)[0].querySelector("pre")).toBeNull();  // the argument's tap is its own: the output stays shut
  });

  it("shows a spinner and Waiting for your tap on a step waiting for a tap", async () => {
    const waiting: Tool[] = [{ name: "run_shell", id: "c1", done: false, state: "wait", args: { command: "rm a.txt" } }];
    const host = await openTrace(waiting);
    const [step] = stepsIn(host);
    expect(step.querySelector('[aria-label="Waiting"]')).not.toBeNull();
    expect(step.textContent).toContain("Waiting for your tap");
    expect(step.querySelector("pre")).toBeNull();
  });

  it("a tap on a step shows the first 12 lines of its output and Show all; that shows everything", async () => {
    const host = await openTrace(receipt);
    const step = stepsIn(host)[0];
    expect(step.querySelector("pre")).toBeNull();
    expect(step.textContent).toContain("38 lines · tap to see them");
    await act(async () => buttonNamed(step, "Ran a command")!.click());
    const pre = step.querySelector("pre")!;
    expect(pre.textContent!.split("\n")).toHaveLength(12);
    expect(pre.textContent).toContain("file-12.txt");
    expect(pre.textContent).not.toContain("file-13.txt");
    const showAll = buttonNamed(step, "Show all 38 lines")!;
    await act(async () => showAll.click());
    expect(step.querySelector("pre")!.textContent!.split("\n")).toHaveLength(38);
    expect(buttonNamed(step, "Show all")).toBeUndefined();
  });

  it("the meta line opens the output too, and a short output has no Show all", async () => {
    const host = await openTrace(receipt);
    const search = stepsIn(host)[2];
    await act(async () => buttonNamed(search, "5 lines")!.click());
    expect(search.querySelector("pre")!.textContent).toBe("r1\nr2\nr3\nr4\nr5");
    expect(buttonNamed(search, "Show all")).toBeUndefined();
  });

  it("a step you said no to has no output region", async () => {
    const host = await openTrace(receipt);
    const no = stepsIn(host)[3];
    const header = buttonNamed(no, "Ran a command");
    if (header) await act(async () => header.click());
    expect(no.querySelector("pre")).toBeNull();
    expect(no.querySelector("[aria-expanded]:not([data-arg])")).toBeNull();  // nothing to open
  });

  it("a step with no output says so and opens nothing", async () => {
    const host = await openTrace(receipt);
    const you = stepsIn(host)[1];
    expect(you.textContent).toContain("No output");
    expect(you.querySelector("[aria-expanded]:not([data-arg])")).toBeNull();
  });

  it("still renders a tool it has no label for", async () => {
    const host = await openTrace([{ name: "GMAIL_FETCH_EMAILS", id: "c1", done: true, state: "done", args: { max: 3 }, result: "one" }]);
    const [step] = stepsIn(host);
    expect(step.textContent).toContain("Used gmail fetch emails");
    expect(step.textContent).toContain("max: 3");
  });

  it("renders old name-only history as just the label", async () => {
    const host = await openTrace([{ name: "now", done: true }]);
    const [step] = stepsIn(host);
    expect(step.textContent).toBe("Checked the time");
    expect(step.querySelectorAll("button")).toHaveLength(0);
  });
});
