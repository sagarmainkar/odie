import { describe, expect, it } from "vitest";
import { readBlocks } from "../parse";

const badge = (text: string) => ({ type: "badge", text });
const stat = (label: string) => ({ type: "stat", label, value: 1 });

describe("containers", () => {
  it("draws a section holding a table and a callout (the spec's phone example)", () => {
    const r = readBlocks(JSON.stringify([{ type: "section", title: "Top 3", children: [
      { type: "table", columns: ["Phone", "Price"], rows: [["Pixel", "₹44,999"]] },
      { type: "callout", tone: "tip", text: "Pixel if photos matter." }] }]))!;
    expect(r.dropped).toEqual([]);
    expect(r.blocks.map((b) => b.type)).toEqual(["section"]);
    expect((r.blocks[0] as any).children.map((b: any) => b.type)).toEqual(["table", "callout"]);
    expect((r.blocks[0] as any).collapsed).toBe(false);
  });
  it("reads a collapsed section (an accordion), giving it a title to tap when it has none", () => {
    const r = readBlocks(JSON.stringify([{ type: "section", collapsed: true, items: [badge("x")] }]))!;
    expect(r.blocks).toEqual([{ type: "section", title: "Details", collapsed: true, children: [{ type: "badge", text: "x" }] }]);
  });
  it("keeps a row or grid one level down, and flattens anything deeper", () => {
    const r = readBlocks(JSON.stringify([{ type: "section", title: "S", children: [
      { type: "row", children: [stat("a"), { type: "grid", children: [stat("b"), stat("c")] }] },
      { type: "grid", children: [stat("d"), stat("e")] }] }]))!;
    const section = r.blocks[0] as any;
    expect(section.children.map((b: any) => b.type)).toEqual(["row", "grid"]);
    // The grid two levels down is gone; its stats sit in the row instead.
    expect(section.children[0].children.map((b: any) => b.label)).toEqual(["a", "b", "c"]);
    expect(r.dropped).toEqual([{ path: "0.children.0.children.1", why: "grid nested too deep; drawn in place" }]);
  });
  it("flattens a section inside a section into a heading and its children", () => {
    const r = readBlocks(JSON.stringify([{ type: "section", children: [badge("a"), { type: "section", title: "More", children: [badge("b")] }] }]))!;
    expect((r.blocks[0] as any).children).toEqual([{ type: "badge", text: "a" }, { type: "heading", text: "More" }, { type: "badge", text: "b" }]);
  });
  it("draws a row holding a wide block as a plain stack", () => {
    const r = readBlocks(JSON.stringify([{ type: "row", children: [stat("a"), { type: "list", items: ["x"] }] }]))!;
    expect(r.blocks.map((b) => b.type)).toEqual(["stat", "list"]);
    expect(r.dropped[0].why).toBe("a list can't sit in a row; drawn as a stack");
  });
  it("drops an empty container, and one whose children are all broken", () => {
    const r = readBlocks(JSON.stringify([{ type: "grid", children: [] }, { type: "row", children: [{ type: "badge" }] }]))!;
    expect(r.blocks).toEqual([]);
    expect(r.dropped).toEqual([
      { path: "0", why: "grid has no children it can draw" },
      { path: "1.children.0", why: "badge needs text" },
      { path: "1", why: "row has no children it can draw" },
    ]);
  });
  it("draws a container with one child as just that child, and keeps at most 3 in a row and 6 in a grid", () => {
    expect(readBlocks(JSON.stringify([{ type: "row", children: [badge("solo")] }]))!.blocks).toEqual([{ type: "badge", text: "solo" }]);
    const row = readBlocks(JSON.stringify([{ type: "row", children: [badge("1"), badge("2"), badge("3"), badge("4")] }]))!;
    expect((row.blocks[0] as any).children.length).toBe(3);
    const grid = readBlocks(JSON.stringify([{ type: "grid", children: Array.from({ length: 8 }, (_, i) => stat(`s${i}`)) }]))!;
    expect((grid.blocks[0] as any).children.length).toBe(6);
    expect(grid.dropped).toEqual([{ path: "0", why: "kept the first 6 children of 8" }]);
  });
});
