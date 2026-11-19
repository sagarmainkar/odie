// @vitest-environment jsdom
// A card from a newer server can carry a button this app doesn't know yet: the tap says so on that card and offers
// the reload, instead of doing nothing (or dropping the card).
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Need, NeedAction } from "../needs";
import { knowsAction } from "../needs";
import { NeedsYou } from "./NeedsYou";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let unmount: (() => void) | null = null;
afterEach(() => { unmount?.(); unmount = null; document.body.innerHTML = ""; });

const newer: Need = {
  ref: "job:9", title: "Tidy the photos folder", why: "Odie's job", icon: "rupee", badge: "Needs you", ask: "",
  main: { label: "Pause it", action: "job_pause" as NeedAction["action"], value: "j9" },
  other: { label: "Done", action: "dismiss", value: "job:9" },
};

async function draw(items: Need[], onAct: (n: Need, a: NeedAction) => void) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => root.render(<NeedsYou items={items} footer="" closed={[]} onAct={onAct} onReopen={() => {}} />));
  unmount = () => act(() => root.unmount());
  return host;
}

function button(host: HTMLElement, label: string): HTMLButtonElement {
  const found = [...host.querySelectorAll("button")].find((b) => b.textContent === label);
  if (!found) throw new Error(`no button ${label}`);
  return found;
}

describe("a button from a newer server", () => {
  it("knows the actions this app handles, and not others", () => {
    expect(knowsAction("job_allow")).toBe(true);
    expect(knowsAction("show_output")).toBe(true);
    expect(knowsAction("job_pause")).toBe(false);
  });

  it("an unknown action shows the reload hint on its card and calls nothing", async () => {
    const onAct = vi.fn();
    const host = await draw([newer], onAct);
    expect(host.textContent).not.toContain("This needs the new version");
    await act(async () => button(host, "Pause it").click());
    expect(onAct).not.toHaveBeenCalled();
    expect(host.textContent).toContain("This needs the new version");
    expect(button(host, "Reload")).toBeTruthy();
    await act(async () => button(host, "Done").click());
    expect(onAct).toHaveBeenCalledTimes(1);  // the buttons it knows still work
  });
});
