// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import catalog from "../../../odie/blocks/catalog.json";
import { ICON_NAMES } from "../components/Tile";
import { parseImages } from "../components/ImageStrip";
import { cleanSvg } from "../svgBlock";
import { readBlocks } from "./parse";

describe("block catalogue", () => {
  it("every example draws as its kind, with nothing dropped (containers keep all their children)", () => {
    for (const b of catalog.blocks as any[]) {
      if ((b.fence ?? "odie-blocks") === "odie-images") {
        expect(parseImages(JSON.stringify(b.example)), b.kind).not.toBeNull();
        continue;
      }
      if (b.fence === "odie-svg") {
        expect(cleanSvg(b.example), b.kind).not.toBeNull();
        continue;
      }
      const out = readBlocks(JSON.stringify([b.example]))!;
      expect(out.blocks.length, b.kind).toBe(1);
      expect(out.blocks[0].type).toBe(b.kind);
      expect(out.dropped, b.kind).toEqual([]);
      if ("children" in out.blocks[0]) expect(out.blocks[0].children.length, b.kind).toBe(b.example.children.length);
    }
  });
  it("draws each of the chart's gallery examples as its own kind, with nothing dropped", () => {
    const chart = (catalog.blocks as any[]).find((b) => b.kind === "chart");
    const kinds = [];
    for (const example of chart.more_examples) {
      const out = readBlocks(JSON.stringify([example]))!;
      expect(out.dropped, example.kind).toEqual([]);
      const block = out.blocks[0];
      expect(block.type === "chart" && block.spec.type, example.kind).toBe(example.kind);
      kinds.push(example.kind);
    }
    expect(kinds.sort()).toEqual(["area", "combo", "donut", "hbar", "pie", "stacked"]);
  });
  it("draws the shared-values example whole, its text using the calculator's inputs", () => {
    const out = readBlocks(JSON.stringify(catalog.shared_example))!;
    expect(out.blocks.map((b) => b.type)).toEqual(["calculator", "callout"]);
    expect(out.dropped).toEqual([]);
  });
  it("makes every list item tappable with a follow-up question, in the fields and the example", () => {
    const list = (catalog.blocks as any[]).find((b) => b.kind === "list");
    expect(list.fields).toContain("run: a follow-up the user might ask");
    for (const item of list.example.items) expect(typeof item.run, item.title).toBe("string");
  });
  it("leads the calculator with EMI and loan questions, and says not to do those sums in text", () => {
    const calc = (catalog.blocks as any[]).find((b) => b.kind === "calculator");
    expect(calc.use_when.startsWith("EMI, loan, SIP")).toBe(true);
    expect(calc.use_when).toContain("never work out EMIs, interest or returns yourself");
  });
  it("lists only icons the app has", () => {
    for (const i of catalog.icons) expect(ICON_NAMES, i).toContain(i);
  });
  it("uses only known icons in its inline :icon[…] examples", () => {
    const text = JSON.stringify(catalog);
    for (const m of text.matchAll(/:icon\[([\w-]+)\]/g)) expect(catalog.icons, m[1]).toContain(m[1]);
  });
});
