// @vitest-environment jsdom
// Phase 3 (19 Nov 2026): every card Odie makes is a loop with "Why?" (its evidence, each line with its time) and a
// small menu with Split, for when two things were wrongly made one. Split never sits among the three buttons the Mac
// app reads; the busy/tap guard covers it like Merge.
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { splitReady, type Need } from "../needs";
import { SETTLE_MS } from "../tapGuard";
import { NeedsYou } from "./NeedsYou";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;
let host: HTMLElement;
beforeEach(() => {
  vi.useFakeTimers();
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root?.unmount());
  root = null;
  document.body.innerHTML = "";
  vi.useRealTimers();
});

const invoices: Need = {
  ref: "loop:7", title: "Pay Northwind invoices", why: "₹4,000 due 25 Nov", icon: "rupee", badge: "₹4,000",
  ask: "Tell me about loop #7: Pay Northwind invoices",
  main: { label: "Tell me more", action: "chat", value: "Tell me about loop #7: Pay Northwind invoices" },
  other: { label: "Done", action: "loop_done", value: 7 }, later: { label: "Later", action: "later", value: "loop:7" },
  evidence: [{ id: 31, at: "2026-11-19T09:00:00+05:30", source: "mail", fact: "Invoice INV-101: ₹4,000 due 25 Nov" },
             { id: 32, at: "2026-11-19T09:05:00+05:30", source: "mail", fact: "Invoice INV-102: ₹9,500 due 30 Nov" }],
  more: [{ label: "Split", action: "split", value: 7 }],
};

const settle = () => act(async () => { vi.advanceTimersByTime(SETTLE_MS + 50); });

function byText(label: string): HTMLButtonElement {
  const found = [...host.querySelectorAll("button")].find((b) => b.textContent === label || b.getAttribute("aria-label") === label);
  if (!found) throw new Error(`no ${label}`);
  return found;
}

describe("a loop's card: Why? and Split", () => {
  it("Why? shows each line of evidence with its time", async () => {
    await act(async () => root!.render(<NeedsYou items={[invoices]} footer="" closed={[]} onAct={() => {}} onReopen={() => {}} />));
    await settle();
    await act(async () => byText("Why?").click());
    const why = host.querySelector('[aria-label="Why"]')!.textContent!;
    expect(why).toContain("09:00 Invoice INV-101");
    expect(why).toContain("09:05 Invoice INV-102");
  });

  it("Split moves the picked lines to a card of their own, once, and keeps the three buttons as they were", async () => {
    const onSplit = vi.fn(async () => {});
    await act(async () => root!.render(<NeedsYou items={[invoices]} footer="" closed={[]} onAct={() => {}} onReopen={() => {}} onSplit={onSplit} />));
    await settle();
    const buttons = [...host.querySelectorAll("[data-buttons] button")].map((b) => b.textContent);
    expect(buttons).toEqual(["Tell me more", "Done", "Later"]);  // Split is not one of them
    await act(async () => byText("More").click());
    await act(async () => byText("Split…").click());
    const go = byText("Make it a separate card");
    expect(go.disabled).toBe(true);  // nothing picked yet
    const second = host.querySelectorAll('[aria-label="Split"] input[type="checkbox"]')[1] as HTMLInputElement;
    await act(async () => second.click());
    expect(byText("Make it a separate card").disabled).toBe(false);
    await act(async () => { byText("Make it a separate card").click(); });
    expect(onSplit).toHaveBeenCalledTimes(1);
    expect(onSplit).toHaveBeenCalledWith(7, [32]);
  });

  it("a card with one line of evidence has nothing to split", async () => {
    const one = { ...invoices, evidence: invoices.evidence!.slice(0, 1) };
    await act(async () => root!.render(<NeedsYou items={[one]} footer="" closed={[]} onAct={() => {}} onReopen={() => {}} />));
    await settle();
    await act(async () => byText("More").click());
    expect(host.textContent).toContain("Nothing to split");
  });
});

describe("a loop's card: Less like this and Forget this (phase 5)", () => {
  const menu = { ...invoices, more: [{ label: "Split", action: "split" as const, value: 7 },
    { label: "Less like this", action: "less_like_this" as const, value: 7 }, { label: "Forget this", action: "forget" as const, value: 7 }] };

  it("Less like this goes at once, through onMenu", async () => {
    const onMenu = vi.fn(async () => {});
    await act(async () => root!.render(<NeedsYou items={[menu]} footer="" closed={[]} onAct={() => {}} onReopen={() => {}} onMenu={onMenu} />));
    await settle();
    await act(async () => byText("More").click());
    await act(async () => { byText("Less like this").click(); });
    expect(onMenu).toHaveBeenCalledTimes(1);
    expect((onMenu.mock.calls[0] as unknown[])[1]).toMatchObject({ action: "less_like_this", value: 7 });
  });

  it("Forget this asks first, and Cancel forgets nothing", async () => {
    const onMenu = vi.fn(async () => {});
    await act(async () => root!.render(<NeedsYou items={[menu]} footer="" closed={[]} onAct={() => {}} onReopen={() => {}} onMenu={onMenu} />));
    await settle();
    await act(async () => byText("More").click());
    await act(async () => byText("Forget this…").click());
    expect(host.textContent).toContain("can't be brought back");
    await act(async () => byText("Cancel").click());
    expect(onMenu).not.toHaveBeenCalled();
    await act(async () => byText("More").click());
    await act(async () => byText("Forget this…").click());
    await act(async () => { byText("Forget it").click(); });
    expect(onMenu).toHaveBeenCalledTimes(1);
    expect((onMenu.mock.calls[0] as unknown[])[1]).toMatchObject({ action: "forget", value: 7 });
  });
});

describe("splitReady", () => {
  it("needs at least one line picked and never all of them", () => {
    expect(splitReady(1, 3)).toBe(true);
    expect(splitReady(0, 3)).toBe(false);
    expect(splitReady(3, 3)).toBe(false);
    expect(splitReady(1, 1)).toBe(false);
  });
});
