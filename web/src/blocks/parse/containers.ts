// Containers: row, section and grid hold other blocks. Nesting goes one level deep: a top-level container may hold a
// row or a grid, and nothing deeper. Anything deeper is flattened (its children drawn in its place), never dropped.
import type { Block } from "../parse";
import { clean, firstList, firstText, keepFirst, type Trail } from "./fields";

export type RowBlock = { type: "row"; children: Block[] };
export type SectionBlock = { type: "section"; title?: string; collapsed: boolean; children: Block[] };
export type GridBlock = { type: "grid"; children: Block[] };
export type ContainerBlock = RowBlock | SectionBlock | GridBlock;

export const CONTAINER_KINDS = ["row", "section", "grid"];

// Blocks too wide to sit side by side: a row holding one of these is drawn as a plain stack instead.
const WIDE_KINDS = ["chart", "tiles", "timeline", "progress", "streak", "flip", "heatmap", "table", "list", "checklist", "calculator", "section", "grid"];

const MAX_IN_ROW = 3;
const MAX_IN_GRID = 6;

/** Reads one item of a container's children into blocks (a flattened container gives several). Passed in by
 *  parse.ts so this file doesn't import it back. `depth` counts the containers above the item. */
export type ReadChild = (raw: unknown, here: Trail, depth: number) => Block[];

/**
 * A row, section or grid → the container block, or its children in its place (flattened), or nothing.
 * Children are in `children` (also `items`, `blocks`, `content`); each child is read like a top-level block.
 * - depth 0 (top level): any container is drawn.
 * - depth 1 (inside a container): a row or grid is drawn; a section is flattened into a heading (its title) and its
 *   children.
 * - depth 2 or more: every container is flattened.
 * - A row holding a wide block (a table, a chart…) is flattened; a row or grid with one child is just that child.
 * - At most 3 children in a row and 6 in a grid (the rest dropped, with a note). An empty container is dropped.
 * - section: title (optional; also `label`), collapsed: true makes it an accordion closed by default.
 * Example at the top level:
 *   {type: "section", title: "Picks", children: [{type: "badge", text: "New"}, {type: "section", title: "More", children: [{type: "divider"}]}]}
 *   → [{type: "section", title: "Picks", collapsed: false, children: [{type: "badge", text: "New"}, {type: "heading", text: "More"}, {type: "divider"}]}]
 */
export function readContainer(raw: any, here: Trail, depth: number, readChild: ReadChild): Block[] {
  const kind: string = raw.type;
  const list = firstList([raw.children, raw.items, raw.blocks, raw.content]) ?? [];

  // Too deep? Then this container won't be drawn: its children take its place, at its depth.
  const deepestAllowed = kind === "section" ? 0 : 1;
  const flatten = depth > deepestAllowed;
  const childDepth = flatten ? depth : depth + 1;

  let children: Block[] = [];
  list.forEach((child, i) => {
    children.push(...readChild(child, here.at("children").at(i), childDepth));
  });
  if (!children.length) {
    here.drop(`${kind} has no children it can draw`);
    return [];
  }

  // A section's title is kept: on the drawn section, or as a heading when the section is flattened.
  const title = firstText([raw.title, raw.label], 60);
  if (flatten) {
    here.drop(`${kind} nested too deep; drawn in place`);
    if (kind === "section" && title) return [{ type: "heading", text: title }, ...children];
    return children;
  }

  if (kind === "section") {
    const collapsed = raw.collapsed === true;
    let shownTitle = title;
    if (!shownTitle && collapsed) shownTitle = "Details";  // a closed accordion needs something to tap
    return [clean({ type: "section" as const, title: shownTitle, collapsed, children })];
  }

  // Row and grid from here on.
  const wide = children.find((b) => WIDE_KINDS.includes(b.type));
  if (kind === "row" && wide) {
    here.drop(`a ${wide.type} can't sit in a row; drawn as a stack`);
    return children;
  }
  if (children.length === 1) return children;
  if (kind === "row") {
    children = keepFirst(children, MAX_IN_ROW, here, "children");
    return [{ type: "row", children }];
  }
  children = keepFirst(children, MAX_IN_GRID, here, "children");
  return [{ type: "grid", children }];
}
