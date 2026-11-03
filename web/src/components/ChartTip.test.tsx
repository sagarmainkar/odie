// @vitest-environment jsdom
// The hover card every chart shares (ChartTip.tsx): where it goes, what it shows, and the keys that step through a
// chart's points (chartPick.ts).
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { ChartTip, type Tip } from "./ChartTip";
import { tipPlace } from "./chartGeometry";
import { stepPick } from "./chartPick";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe("tipPlace", () => {
  it("sits 12px right of and above the pointer", () => {
    expect(tipPlace(100, 200, 120, 60, 600)).toEqual({ left: 112, top: 128 });
  });
  it("flips to the left near the right edge", () => {
    expect(tipPlace(550, 200, 120, 60, 600)).toEqual({ left: 418, top: 128 });
  });
  it("drops below the pointer near the top", () => {
    expect(tipPlace(100, 20, 120, 60, 600)).toEqual({ left: 112, top: 34 });
  });
  it("stays inside the chart on every side", () => {
    expect(tipPlace(50, 200, 120, 60, 100).left).toBe(2);              // a card wider than room either side
    expect(tipPlace(100, 30, 120, 60, 600, 80)).toEqual({ left: 112, top: 18 });  // pushed below, held at the bottom
  });
});

describe("stepPick", () => {
  it("moves with the arrow keys and stops at the ends", () => {
    expect(stepPick(null, "ArrowRight", 5)).toBe(0);
    expect(stepPick(null, "ArrowLeft", 5)).toBe(4);
    expect(stepPick(2, "ArrowRight", 5)).toBe(3);
    expect(stepPick(4, "ArrowRight", 5)).toBe(4);
    expect(stepPick(0, "ArrowLeft", 5)).toBe(0);
  });
  it("hides on Escape and ignores other keys", () => {
    expect(stepPick(3, "Escape", 5)).toBeNull();
    expect(stepPick(3, "Enter", 5)).toBeUndefined();
    expect(stepPick(3, "ArrowDown", 5)).toBeUndefined();
  });
  it("moves with up and down too for rows", () => {
    expect(stepPick(1, "ArrowDown", 5, true)).toBe(2);
    expect(stepPick(1, "ArrowUp", 5, true)).toBe(0);
  });
});

describe("ChartTip", () => {
  const tip: Tip = { x: 10, y: 10, title: "Q3", rows: [{ colour: "var(--t-chart-1)", name: "Revenue", value: "4,213,500,000" }], note: "40% of total" };
  let box: HTMLDivElement;
  let root: Root;
  beforeEach(() => {
    box = document.createElement("div");
    document.body.append(box);
    root = createRoot(box);
  });
  afterEach(() => {
    act(() => root.unmount());
    box.remove();
  });

  it("shows the title, a row per series with its swatch and full value, and the note", () => {
    act(() => root.render(<ChartTip tip={tip} />));
    const card = box.querySelector(".chart-tip")!;
    expect(card.classList.contains("chart-tip-on")).toBe(true);
    expect(card.querySelector(".chart-tip-title")!.textContent).toBe("Q3");
    expect(card.querySelector(".chart-tip-name")!.textContent).toBe("Revenue");
    expect(card.querySelector(".chart-tip-value")!.textContent).toBe("4,213,500,000");
    expect((card.querySelector(".chart-tip-row i") as HTMLElement).style.background).toBe("var(--t-chart-1)");
    expect(card.querySelector(".chart-tip-note")!.textContent).toBe("40% of total");
  });

  it("fades out keeping its last contents when hidden", () => {
    act(() => root.render(<ChartTip tip={tip} />));
    act(() => root.render(<ChartTip tip={null} />));
    const card = box.querySelector(".chart-tip")!;
    expect(card.classList.contains("chart-tip-on")).toBe(false);
    expect(card.textContent).toContain("Q3");
  });
});
