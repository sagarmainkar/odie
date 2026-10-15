// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ReplyPlace } from "../blocks/SavedPlace";
import { loadDiagrams } from "../lazy";
import { Diagram } from "./Diagram";

// jsdom can't lay out text, so Mermaid itself is swapped for a stand-in here; the real one is checked in a browser.
const drawDiagram = vi.fn();
vi.mock("../lazy", () => ({ loadDiagrams: vi.fn(async () => ({ drawDiagram })) }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  vi.clearAllMocks();
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

const FLOW = "flowchart TD\n  A[Apply] --> B[Approve]";

describe("a mermaid diagram", () => {
  it("fetches Mermaid and draws the SVG it returns", async () => {
    drawDiagram.mockResolvedValue('<svg viewBox="0 0 420 300"><text>Apply</text></svg>');
    await act(async () => root.render(<Diagram code={FLOW} />));
    expect(loadDiagrams).toHaveBeenCalledTimes(1);
    expect(drawDiagram).toHaveBeenCalledWith(FLOW, false);
    const box = host.querySelector<HTMLDivElement>(".diagram")!;
    expect(box.querySelector("svg text")?.textContent).toBe("Apply");
    expect(box.style.getPropertyValue("--drawn-w")).toBe("420px");
  });

  it("shows the text as written with a short note when the text has a mistake", async () => {
    drawDiagram.mockRejectedValue(new Error("Parse error on line 2:\n...A[Apply --> \n-----^\nExpecting 'SQE'"));
    const broken = "flowchart TD\n  A[Apply --> ";
    await act(async () => root.render(<Diagram code={broken} />));
    expect(host.querySelector(".diagram")).toBeNull();
    expect(host.querySelector(".diagram-note")?.textContent).toBe("Couldn’t draw this diagram: Parse error on line 2:");
    expect(host.querySelector(".diagram-broken pre")?.textContent).toBe(broken);
  });

  it("waits for the whole reply before drawing", async () => {
    await act(async () => root.render(
      <ReplyPlace.Provider value={{ text: "", streaming: true }}><Diagram code={FLOW} /></ReplyPlace.Provider>,
    ));
    expect(loadDiagrams).not.toHaveBeenCalled();
    expect(host.querySelector('[aria-label="Drawing chart"]')).not.toBeNull();
  });

  it("draws in the night colours at night", async () => {
    drawDiagram.mockResolvedValue('<svg viewBox="0 0 100 100"></svg>');
    document.documentElement.dataset.tod = "night";
    await act(async () => root.render(<Diagram code={FLOW} />));
    expect(drawDiagram).toHaveBeenCalledWith(FLOW, true);
    delete document.documentElement.dataset.tod;
  });
});
