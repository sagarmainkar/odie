// @vitest-environment jsdom
// The Threads drawer belongs to the chat: when the screen changes underneath it (a tab, a link, the hash typed in),
// it closes instead of staying over Settings or Today.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ThreadsSheet } from "./ThreadsSheet";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let unmount: (() => void) | null = null;
afterEach(() => { unmount?.(); unmount = null; document.body.innerHTML = ""; vi.unstubAllGlobals(); });

async function openSheet(open: boolean) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ threads: [] }), { status: 200 })));
  const onClose = vi.fn();
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => root.render(<ThreadsSheet open={open} current={null} pickThread={null} onClose={onClose} onOpen={() => {}} />));
  unmount = () => act(() => root.unmount());
  return onClose;
}

async function goTo(hash: string) {
  await act(async () => {
    window.location.hash = hash;
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  });
}

describe("the Threads drawer", () => {
  it("keeps one listener while the chat redraws, so a hash change the app redraws on still reaches it", async () => {
    // In the browser, App hears the hash change first and React redraws the chat before the drawer's listener runs.
    // A listener swapped during that redraw (a new onClose each render) is skipped by the browser for that event, and
    // the drawer stayed open over Settings. jsdom runs no redraw between listeners, so this checks the cause instead:
    // a redraw with a new onClose must not take the listener off and put a new one on.
    window.location.hash = "#chat";
    await new Promise((done) => setTimeout(done, 0));  // jsdom's own hashchange for this goes by first
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ threads: [] }), { status: 200 })));
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    const first = vi.fn();
    await act(async () => root.render(<ThreadsSheet open current={null} pickThread={null} onClose={first} onOpen={() => {}} />));
    unmount = () => act(() => root.unmount());
    const removed = vi.spyOn(window, "removeEventListener");
    const second = vi.fn();
    await act(async () => root.render(<ThreadsSheet open current={null} pickThread={null} onClose={second} onOpen={() => {}} />));
    const hashListenersRemoved = removed.mock.calls.filter((call) => String(call[0]) === "hashchange");
    expect(hashListenersRemoved).toEqual([]);
    await goTo("#settings");
    expect(second).toHaveBeenCalled();  // the newest onClose is the one called
    expect(first).not.toHaveBeenCalled();
    removed.mockRestore();
  });
  it("closes when the screen changes underneath it", async () => {
    window.location.hash = "#chat";
    const onClose = await openSheet(true);
    expect(document.querySelector("[role=dialog][aria-label=Threads]")).not.toBeNull();
    await goTo("#settings");
    expect(onClose).toHaveBeenCalled();
  });
  it("asks nothing while it is closed", async () => {
    window.location.hash = "#chat";
    const onClose = await openSheet(false);
    await goTo("#settings");
    expect(onClose).not.toHaveBeenCalled();
  });
});
