// @vitest-environment jsdom
// The desktop Threads sidebar folds away and comes back: its own button hides it, the header's Threads pill brings it
// back, Cmd+\ / Ctrl+\ toggles it, and this device remembers the choice. Wired the way Chat wires it.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HIDDEN, SIDEBAR_KEY, useThreadsSidebar } from "../threadsSidebar";
import { ThreadsPill, ThreadsSidebar } from "./ThreadsSheet";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let unmount: (() => void) | null = null;
afterEach(() => {
  unmount?.(); unmount = null;
  document.body.innerHTML = "";
  localStorage.clear();
  vi.unstubAllGlobals();
});

function ChatLike({ wide, onSheet }: { wide: boolean; onSheet: () => void }) {
  const sidebar = useThreadsSidebar(wide);
  function pressPill() {
    if (wide) sidebar.setOpen(true);
    else onSheet();
  }
  return (
    <>
      {wide && <ThreadsSidebar open={sidebar.open} onHide={() => sidebar.setOpen(false)} current={null} pickThread={null}
        onOpen={() => {}} onNewChat={() => {}} reload={0} />}
      <ThreadsPill wide={wide} sidebarOpen={sidebar.open} onPress={pressPill} />
    </>
  );
}

async function show(wide: boolean) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ threads: [] }), { status: 200 })));
  const onSheet = vi.fn();
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => root.render(<ChatLike wide={wide} onSheet={onSheet} />));
  unmount = () => act(() => root.unmount());
  return onSheet;
}

const sidebar = () => document.querySelector<HTMLElement>(".threads-sidebar");
const button = (label: string) => document.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`);

async function press(key: string, mods: KeyboardEventInit = {}) {
  await act(async () => { window.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...mods })); });
}

describe("the desktop Threads sidebar", () => {
  it("is open by default, with no Threads pill in the header", async () => {
    await show(true);
    expect(sidebar()?.dataset.open).toBe("true");
    expect(button("Hide threads")).not.toBeNull();
    expect(button("Show threads")).toBeNull();
  });

  it("hides with its own button, the pill brings it back, and the device remembers each", async () => {
    await show(true);
    await act(async () => button("Hide threads")!.click());
    expect(sidebar()?.dataset.open).toBe("false");
    expect(sidebar()?.hasAttribute("inert")).toBe(true);  // hidden rows can't be tabbed to (jsdom has the attribute, not the property)
    expect(localStorage.getItem(SIDEBAR_KEY)).toBe(HIDDEN);
    expect(button("Show threads")).not.toBeNull();

    await act(async () => button("Show threads")!.click());
    expect(sidebar()?.dataset.open).toBe("true");
    expect(sidebar()?.hasAttribute("inert")).toBe(false);
    expect(button("Show threads")).toBeNull();
    expect(localStorage.getItem(SIDEBAR_KEY)).toBeNull();
  });

  it("stays hidden after a reload", async () => {
    localStorage.setItem(SIDEBAR_KEY, HIDDEN);
    await show(true);
    expect(sidebar()?.dataset.open).toBe("false");
    expect(button("Show threads")).not.toBeNull();
  });

  it("toggles on Ctrl+\\ (jsdom is not a Mac), but a typed backslash is left alone", async () => {
    await show(true);
    await press("\\");
    expect(sidebar()?.dataset.open).toBe("true");
    await press("\\", { ctrlKey: true });
    expect(sidebar()?.dataset.open).toBe("false");
    await press("\\", { ctrlKey: true });
    expect(sidebar()?.dataset.open).toBe("true");
  });
});

describe("below 1024px", () => {
  it("keeps the Threads pill, which opens the sheet as before, and no shortcut", async () => {
    localStorage.setItem(SIDEBAR_KEY, HIDDEN);  // a choice made on the wide screen changes nothing here
    const onSheet = await show(false);
    expect(sidebar()).toBeNull();
    const pill = button("Threads");
    expect(pill).not.toBeNull();
    await act(async () => pill!.click());
    expect(onSheet).toHaveBeenCalledTimes(1);
    await press("\\", { ctrlKey: true });
    expect(localStorage.getItem(SIDEBAR_KEY)).toBe(HIDDEN);
  });
});
