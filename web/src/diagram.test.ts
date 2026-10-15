// @vitest-environment jsdom
import { describe, expect, it, vi } from "vitest";

// What Mermaid is told and what reaches the page. Mermaid is a stand-in (jsdom can't lay out a real diagram) that
// returns an SVG with things a hostile diagram might try to slip in.
const mermaid = vi.hoisted(() => ({
  initialize: vi.fn(),
  render: vi.fn(async () => ({
    svg: '<svg viewBox="0 0 10 10" onload="alert(1)"><script>alert(2)</script><text>Hi</text><foreignObject><img src=x onerror="alert(3)"></foreignObject></svg>',
  })),
}));
vi.mock("mermaid", () => ({ default: mermaid }));

describe("drawDiagram", () => {
  it("runs Mermaid strict, with plain-text labels, and cleans the SVG before it reaches the page", async () => {
    const { drawDiagram } = await import("./diagram");
    const svg = await drawDiagram("flowchart TD\n  A --> B", false);
    const config = mermaid.initialize.mock.calls[0][0];
    expect(config.securityLevel).toBe("strict");
    expect(config.htmlLabels).toBe(false);
    expect(config.flowchart.htmlLabels).toBe(false);
    expect(svg).toContain("<text>Hi</text>");
    expect(svg).not.toMatch(/script|onload|onerror|<img|foreignObject/);
  });

  it("uses the night colours at night", async () => {
    const { drawDiagram } = await import("./diagram");
    await drawDiagram("flowchart TD\n  A --> B", true);
    const config = mermaid.initialize.mock.calls.at(-1)![0];
    expect(config.themeVariables.darkMode).toBe(true);
  });
});
