// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getJSON, putJSON } from "../api";
import { forgetMode } from "../approvalsMode";
import { ApprovalsSection } from "./ApprovalsSection";

vi.mock("../api", async (real) => ({ ...(await real<typeof import("../api")>()), getJSON: vi.fn(), putJSON: vi.fn() }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

async function mount(node: React.ReactNode) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => root.render(node));
  await act(async () => { await Promise.resolve(); });  // the mode arrives
  return { host, done: () => act(() => root.unmount()) };
}

function radios(host: HTMLElement) {
  return [...host.querySelectorAll("[role=radio]")].map((b) => [b.textContent, b.getAttribute("aria-checked")]);
}

describe("Settings → Approvals", () => {
  beforeEach(() => { forgetMode(); vi.mocked(putJSON).mockReset(); });

  it("shows both choices, with the saved one checked and its line underneath", async () => {
    vi.mocked(getJSON).mockResolvedValue({ mode: "smart" });
    const view = await mount(<ApprovalsSection />);
    expect(radios(view.host)).toEqual([["Careful", "false"], ["Smart", "true"]]);
    expect(view.host.textContent).toContain("reading secrets always ask");
    await view.done();
  });

  it("saves the other choice when tapped, and the line follows", async () => {
    vi.mocked(getJSON).mockResolvedValue({ mode: "careful" });
    vi.mocked(putJSON).mockResolvedValue({ mode: "smart" });
    const view = await mount(<ApprovalsSection />);
    expect(view.host.textContent).toContain("30-minute pass");
    const smart = [...view.host.querySelectorAll("[role=radio]")].find((b) => b.textContent === "Smart") as HTMLButtonElement;
    await act(async () => { smart.click(); await Promise.resolve(); });
    expect(putJSON).toHaveBeenCalledWith("/api/approvals/mode", { mode: "smart" });
    expect(radios(view.host)).toEqual([["Careful", "false"], ["Smart", "true"]]);
    expect(view.host.textContent).toContain("reading secrets always ask");
    await view.done();
  });

  it("says so when the setting can't be read, and still lets a tap save", async () => {
    vi.mocked(getJSON).mockRejectedValue(new Error("offline"));
    const view = await mount(<ApprovalsSection />);
    expect(view.host.textContent).toContain("Couldn't read this setting");
    const smart = [...view.host.querySelectorAll("[role=radio]")].find((b) => b.textContent === "Smart") as HTMLButtonElement;
    expect(smart.disabled).toBe(false);
    await view.done();
  });

  it("reads an odd answer as Careful", async () => {
    vi.mocked(getJSON).mockResolvedValue({ mode: "yolo" });
    const view = await mount(<ApprovalsSection />);
    expect(radios(view.host)).toEqual([["Careful", "true"], ["Smart", "false"]]);
    await view.done();
  });
});
