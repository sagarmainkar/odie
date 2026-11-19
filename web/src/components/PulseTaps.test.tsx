// @vitest-environment jsdom
// A tap on Pulse must land on the card the user meant. When a card leaves, the next one moves up into its place, so
// for a moment after the list changes every card button ignores taps; Merge, Use this, Allow and Retry keep their
// card in place, busy, until the server answers; Stop can't be sent twice.
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Need, NeedAction } from "../needs";
import type { OnIt as OnItItem } from "../pulse";
import { SETTLE_MS } from "../tapGuard";
import { NeedsYou } from "./NeedsYou";
import { OnIt } from "./OnIt";

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
  vi.unstubAllGlobals();
});

function reminder(id: number, title: string): Need {
  return {
    ref: `task:${id}`, title, why: "Reminder", icon: "rupee", badge: "", ask: `Tell me about task #${id}`,
    main: { label: "Tell me more", action: "chat", value: `Tell me about task #${id}` },
    other: { label: "Done", action: "done_task", value: id }, later: { label: "Later", action: "later", value: `task:${id}` },
  };
}

function tested(loop: number): Need {
  return {
    ref: `loop:${loop}`, title: `example/app #${loop}`, why: "Tested: 12 pass", icon: "terminal", badge: "", ask: "",
    main: { label: "Merge", action: "merge", value: loop }, other: { label: "Done", action: "loop_done", value: loop },
  };
}

async function draw(items: Need[], onAct: (n: Need, a: NeedAction) => Promise<void> | void) {
  await act(async () => root!.render(<NeedsYou items={items} footer="" closed={[]} onAct={onAct} onReopen={() => {}} />));
}

/** The buttons of the card whose title is `title`, by their labels. */
function cardButtons(title: string): HTMLButtonElement[] {
  const card = [...host.querySelectorAll("section > div")].find((d) => d.textContent?.includes(title));
  if (!card) throw new Error(`no card ${title}`);
  return [...card.querySelectorAll("button")];
}

function button(title: string, label: string): HTMLButtonElement {
  const found = cardButtons(title).find((b) => b.textContent === label || b.title === label);
  if (!found) throw new Error(`no ${label} on ${title}`);
  return found;
}

const settle = () => act(async () => { vi.advanceTimersByTime(SETTLE_MS + 50); });

describe("taps on a changing Pulse", () => {
  it("a second tap within the window after the list changed calls nothing; after it, the card under it", async () => {
    const onAct = vi.fn();
    await draw([reminder(1, "Pay rent"), reminder(2, "Call the plumber")], onAct);
    await settle();
    await act(async () => button("Pay rent", "Done").click());
    expect(onAct).toHaveBeenCalledTimes(1);
    await draw([reminder(2, "Call the plumber")], onAct);  // Done took its card away; the next one moved up
    await act(async () => button("Call the plumber", "Done").click());  // the second tap of a double tap
    expect(onAct).toHaveBeenCalledTimes(1);
    await settle();
    await act(async () => button("Call the plumber", "Done").click());
    expect(onAct).toHaveBeenCalledTimes(2);
    expect(onAct.mock.calls[1][0].ref).toBe("task:2");
  });

  it("two tested cards and a double tap on the first's Merge: exactly one /merge call, for that pull request", async () => {
    const posts: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string) => { posts.push(url); return new Response("{}", { status: 200 }); }));
    let finish: () => void = () => {};
    const onAct = async (_n: Need, a: NeedAction) => {
      await fetch(`/api/loops/${a.value}/${a.action}`, { method: "POST" });
      await new Promise<void>((r) => { finish = r; });  // the list is re-read when the server answers
    };
    await draw([tested(1), tested(2)], onAct);
    await settle();
    const first = button("example/app #1", "Merge");
    await act(async () => { first.click(); first.click(); });
    await act(async () => button("example/app #1", "Merging…").click());
    expect(posts).toEqual(["/api/loops/1/merge"]);
    await act(async () => finish());
  });

  it("a busy card keeps its place, says what it is doing and has every button disabled", async () => {
    let finish: () => void = () => {};
    const onAct = vi.fn(() => new Promise<void>((r) => { finish = r; }));
    await draw([tested(1), tested(2)], onAct);
    await settle();
    await act(async () => button("example/app #1", "Merge").click());
    const busy = cardButtons("example/app #1").filter((b) => b.closest("[data-buttons]"));
    expect(busy.map((b) => b.textContent)).toEqual(["Merging…", "Done"]);
    expect(busy.every((b) => b.disabled)).toBe(true);
    expect(button("example/app #2", "Merge").disabled).toBe(false);  // the other card is untouched
    await act(async () => finish());
    expect(button("example/app #1", "Merge").disabled).toBe(false);  // the server answered and the card is still there
  });

  it("a tap during a refresh that changes the list is ignored", async () => {
    const onAct = vi.fn();
    await draw([tested(1), tested(2)], onAct);
    await settle();
    await draw([reminder(3, "Renew the passport"), tested(1), tested(2)], onAct);  // a live refresh put a card on top
    await act(async () => button("Renew the passport", "Done").click());
    await act(async () => button("example/app #1", "Merge").click());
    expect(onAct).not.toHaveBeenCalled();
  });

  it("a button acts on the card it was drawn with, by its ref, never by its place", async () => {
    const onAct = vi.fn();
    await draw([tested(1), tested(2)], onAct);
    await settle();
    await draw([tested(2), tested(1)], onAct);  // reordered: #2 is now where #1 was
    await settle();
    await act(async () => button("example/app #2", "Done").click());
    expect(onAct.mock.calls[0][0].ref).toBe("loop:2");
    expect(onAct.mock.calls[0][1]).toEqual({ label: "Done", action: "loop_done", value: 2 });
  });
});

describe("Stop on On it", () => {
  const jobs: OnItItem[] = [
    { id: 1, title: "Tidy the photos folder", state: "running", next: "", stop: "j1" } as OnItItem,
    { id: 2, title: "Sort the receipts", state: "running", next: "", stop: "j2" } as OnItItem,
  ];

  it("is disabled while its call is in flight, so a second tap sends nothing", async () => {
    let finish: () => void = () => {};
    const onStop = vi.fn(() => new Promise<void>((r) => { finish = r; }));
    await act(async () => root!.render(<OnIt items={jobs} who="Odie" onStop={onStop} />));
    await settle();
    const stop = [...host.querySelectorAll("button")][0];
    await act(async () => { stop.click(); stop.click(); });
    expect(onStop).toHaveBeenCalledTimes(1);
    expect(onStop).toHaveBeenCalledWith("j1");
    expect(stop.disabled).toBe(true);
    expect(stop.textContent).toBe("Stopping…");
    await act(async () => finish());
  });

  it("ignores taps just after the list changed", async () => {
    const onStop = vi.fn(async () => {});
    await act(async () => root!.render(<OnIt items={jobs} who="Odie" onStop={onStop} />));
    await settle();
    await act(async () => root!.render(<OnIt items={jobs.slice(1)} who="Odie" onStop={onStop} />));
    await act(async () => [...host.querySelectorAll("button")][0].click());
    expect(onStop).not.toHaveBeenCalled();
  });
});
