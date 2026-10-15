// Reading a ```odie-blocks fence: JSON from the model → blocks the app can draw. Each kind has its own reader in
// parse/<kind>.ts, with a comment and a worked example. The rule throughout: never show broken JSON as code; drop what
// doesn't fit and note why (the notes are for the model eval; the app ignores them).
import { readActions, type ActionsBlock } from "./parse/actions";
import {
  readBadge, readBar, readButton, readDivider, readHeading, readImage, readLink, readStat, readText,
  type BadgeBlock, type BarBlock, type ButtonBlock, type DividerBlock, type HeadingBlock, type ImageBlock, type LinkBlock, type StatBlock, type TextBlock,
} from "./parse/atoms";
import { readCallout, type CalloutBlock } from "./parse/callout";
import { readCalculator, type CalculatorBlock } from "./parse/calculator";
import { readChart, type ChartBlock } from "./parse/chart";
import { readChecklist, type ChecklistBlock } from "./parse/checklist";
import { readFlip, type FlipBlock } from "./parse/flip";
import { readHeatmap, type HeatmapBlock } from "./parse/heatmap";
import { CONTAINER_KINDS, readContainer, type ContainerBlock } from "./parse/containers";
import { Trail, type Diagnostic } from "./parse/fields";
import { readKpis, type KpisBlock } from "./parse/kpis";
import { readJson } from "./parse/lenientJson";
import { readList, readRankedList, type ListBlock } from "./parse/list";
import { readProgress, type ProgressBlock } from "./parse/progress";
import { readSource, type SourceBlock } from "./parse/source";
import { readStreak, type StreakBlock } from "./parse/streak";
import { readTable, type TableBlock } from "./parse/table";
import { readTiles, type TilesBlock } from "./parse/tiles";
import { readTimeline, type TimelineBlock } from "./parse/timeline";

export type { KpiItem } from "./parse/kpis";
export type { TileItem } from "./parse/tiles";
export type { Step } from "./parse/progress";
export type { Day } from "./parse/streak";
export type { FlipCard } from "./parse/flip";
export type { HeatScale } from "./parse/heatmap";
export type { Stop } from "./parse/timeline";
export type { ListItem } from "./parse/list";
export type { Highlight } from "./parse/table";
export type { ChecklistItem } from "./parse/checklist";
export type { CalcInput, CalcOutput } from "./parse/calculator";
export type { Diagnostic } from "./parse/fields";

export type Block =
  | ChartBlock | KpisBlock | ActionsBlock | SourceBlock | TilesBlock | ProgressBlock | StreakBlock | TimelineBlock | FlipBlock | HeatmapBlock
  | CalloutBlock | TableBlock | ListBlock | ChecklistBlock | CalculatorBlock
  | HeadingBlock | TextBlock | BadgeBlock | ButtonBlock | LinkBlock | ImageBlock | StatBlock | BarBlock | DividerBlock
  | ContainerBlock;

// Every kind that isn't a container, and the function that reads it. A kind missing here is unknown (dropped, noted).
// "ranked", "ranked list" and "ranking" are names models guess for a ranked list when they draw from memory.
const READERS: Record<string, (raw: any, here: Trail) => Block | null> = {
  chart: readChart, kpis: readKpis, actions: readActions, source: readSource, tiles: readTiles,
  progress: readProgress, streak: readStreak, timeline: readTimeline, flip: readFlip, heatmap: readHeatmap,
  callout: readCallout, table: readTable, list: readList, checklist: readChecklist,
  ranked: readRankedList, "ranked list": readRankedList, ranking: readRankedList,
  calculator: readCalculator,
  heading: readHeading, text: readText, badge: readBadge, button: readButton, link: readLink, image: readImage,
  stat: readStat, bar: readBar, divider: readDivider,
};

/** Every block kind the app draws, containers included: "chart", "checklist", "callout", …, "row", "section", "grid". */
export const BLOCK_KINDS: string[] = [...Object.keys(READERS), ...CONTAINER_KINDS];

/**
 * The fence's text → its blocks and the notes on what was dropped; null when it isn't JSON (after readJson's mends) or
 * isn't a list (a lone block object is taken as a list of one).
 *   '[{"type":"badge","text":"New"},{"type":"weather"}]'
 *   → {blocks: [{type: "badge", text: "New"}], dropped: [{path: "1", why: "unknown type \"weather\""}]}
 */
export function readBlocks(text: string): { blocks: Block[]; dropped: Diagnostic[] } | null {
  let data = readJson(text);
  if (data === undefined) return null;
  const isLoneBlock = data !== null && typeof data === "object" && !Array.isArray(data) && typeof (data as any).type === "string";
  if (isLoneBlock) data = [data];
  if (!Array.isArray(data)) return null;

  const top = new Trail();
  const blocks: Block[] = [];
  data.forEach((raw, i) => {
    blocks.push(...readOne(raw, top.at(i), 0));
  });
  return { blocks, dropped: top.dropped };
}

/** Just the blocks (what the app draws); null when the fence isn't a JSON list. Unknown or broken items are skipped. */
export function parseBlocks(text: string): Block[] | null {
  const read = readBlocks(text);
  if (!read) return null;
  return read.blocks;
}

/** One item of the fence (or of a container's children) → zero, one or several blocks (a flattened container gives
 *  its children). `depth` counts the containers above it. */
function readOne(raw: unknown, here: Trail, depth: number): Block[] {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    here.drop("not a block object");
    return [];
  }
  const kind = (raw as any).type;
  if (CONTAINER_KINDS.includes(kind)) return readContainer(raw, here, depth, readOne);
  const read = READERS[kind];
  if (!read) {
    here.drop(`unknown type "${kind}"`);
    return [];
  }
  const block = read(raw, here);
  if (!block) return [];
  return [block];
}

export function formatChange(change: number | null | undefined, unit: "%" | "pt" = "%"): string {
  if (change === null || change === undefined || !isFinite(change)) return "";
  const v = Math.abs(change).toFixed(1);
  const u = unit === "pt" ? " pt" : "%";
  return change > 0 ? `▲ ${v}${u}` : change < 0 ? `▼ ${v}${u}` : `${v}${u}`;
}

/** Money in a currency + scale unit ("₹Cr", "$M", "€B", or just "₹"); null for any other unit. ₹ uses Indian grouping. */
export function formatAmount(v: number, unit: string | undefined): string | null {
  const m = /^([$₹€£¥])(Cr|K|M|B)?$/.exec(unit ?? "");
  if (!m) return null;
  const [, sym, scale] = m;
  const abs = Math.abs(v);
  const n = abs.toLocaleString(sym === "₹" ? "en-IN" : "en-US", { maximumFractionDigits: abs >= 1000 ? 0 : scale ? 1 : 2 });
  return `${v < 0 ? "-" : ""}${sym}${n}${scale === "Cr" ? " Cr" : scale ?? ""}`;
}
