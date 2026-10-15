import { describe, expect, it } from "vitest";
import { looksLikeAFence, scoreChatReply } from "./chatScore";

const fence = (json: unknown, lang = "odie-blocks") => "```" + lang + "\n" + JSON.stringify(json) + "\n```";

describe("scoreChatReply", () => {
  it("reads a drawn blocks fence: kinds, nothing dropped, nothing left undrawn", () => {
    const s = scoreChatReply("Here:\n\n" + fence([{ type: "callout", tone: "tip", text: "Go early." }]));
    expect(s).toMatchObject({ fences: 1, parsed: true, kinds: ["callout"], dropped: [], not_drawn: [] });
  });
  it("finds a one-line ```odie-images … ``` that Markdown reads as inline code, as the owner saw it", () => {
    const reply = 'Coorg looks lovely!\n\n```odie-images: {"title": "Coorg", "images": [{"url": "https://example.com/a.jpg"}]} ```\n\nWant more?';
    const s = scoreChatReply(reply);
    expect(s.fences).toBe(0);
    expect(s.kinds).toEqual([]);
    expect(s.not_drawn).toHaveLength(1);
    expect(s.not_drawn[0].as).toBe("inline code");
    expect(s.not_drawn[0].text).toContain("odie-images:");
  });
  it("finds block JSON shown in a code box, and a fence cut off mid-way left as a placeholder", () => {
    const boxed = scoreChatReply(fence([{ type: "table", columns: ["a"], rows: [["1"]] }], "odie-block"));
    expect(boxed.not_drawn.map((x) => x.as)).toEqual(["code box"]);
    const cut = scoreChatReply('```odie-blocks\n[{"type": "table", "columns": ["a"], "rows":');
    expect(cut).toMatchObject({ fences: 1, parsed: false });
    expect(cut.not_drawn.map((x) => x.as)).toEqual(["stuck placeholder"]);
  });
  it("counts a drawn photo strip and chart, and records items the block parser dropped", () => {
    const images = fence({ images: [{ url: "https://example.com/a.jpg" }] }, "odie-images");
    const chart = fence({ type: "bar", title: "t", x: ["a", "b"], series: [{ name: "s", data: [1, 2] }] }, "odie-chart");
    const weather = fence([{ type: "divider" }, { type: "weather" }]);
    const s = scoreChatReply([images, chart, weather].join("\n\n"));
    expect(s.kinds).toEqual(["images", "chart", "divider"]);
    expect(s.dropped).toEqual([{ path: "f3:1", why: expect.stringContaining("weather") }]);
  });
  it("leaves plain text and ordinary code alone", () => {
    expect(scoreChatReply("Canberra.\n\n```python\nprint(1)\n```\n\nRun `npm ci` first.")).toMatchObject({ fences: 0, parsed: true, kinds: [], not_drawn: [] });
  });
});

describe("looksLikeAFence", () => {
  it("knows block JSON and fence names from ordinary words", () => {
    expect(looksLikeAFence('odie-images: {"images": []}')).toBe(true);
    expect(looksLikeAFence('{"type": "table"}')).toBe(true);
    expect(looksLikeAFence("Here's your plan for Ooty")).toBe(false);
    expect(looksLikeAFence("npm ci")).toBe(false);
  });
});
