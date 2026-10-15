// The shapes models guessed when they drew without loading the visuals skill, taken word for word from the saved chats
// (real test chats; the fences are copied into testdata/forgive-fences.json). Each test reads the exact fence the
// model wrote and checks it now draws, with nothing lost.
import { describe, expect, it } from "vitest";
import fences from "../testdata/forgive-fences.json";
import { parseChart } from "../../components/ChartBlock";
import { readBlocks } from "../parse";
import { closeUnclosedStrings, joinThousands, readJson } from "./lenientJson";

const gemmaChat = "gemma", glmChat = "glm", opusChat = "opus", qwenChat = "qwen";

/** The k-th odie-* fence (from 0) of turn n's reply in a saved chat, exactly as the model wrote it (testdata/forgive-fences.json,
 *  cut from the saved chats, which stay private). */
function fence(chat: string, n: number, k = 0): string {
  return (fences as Record<string, string>)[`${chat}-${n}-${k}`];
}

describe("timeline without groups (Qwen 3.8, Gemma 4)", () => {
  it("draws Qwen's three day timelines, each a flat list of events, with every stop and its text", () => {
    const read = readBlocks(fence(qwenChat, 4))!;
    expect(read.dropped).toEqual([]);
    expect(read.blocks.map((b) => b.type)).toEqual(["timeline", "timeline", "timeline", "callout"]);
    const day1 = read.blocks[0] as any;
    expect(day1.title).toBe("Day 1 — Settle in + easy start");
    expect(day1.groups).toHaveLength(1);
    expect(day1.groups[0].label).toBe("");
    expect(day1.groups[0].items).toHaveLength(5);
    expect(day1.groups[0].items[0]).toEqual({ time: "09:00", title: "Check in, chai & rest",
      note: "Hotel near the lake / town centre. Let parents settle, no sightseeing." });
    expect((read.blocks[2] as any).groups[0].items).toHaveLength(4);
  });
  it("draws Qwen's night-drive plan (a timeline between two callouts)", () => {
    const read = readBlocks(fence(qwenChat, 8))!;
    expect(read.dropped).toEqual([]);
    expect(read.blocks.map((b) => b.type)).toEqual(["callout", "timeline", "callout"]);
  });
  it("takes Gemma's day headings written as the time as the stops' titles", () => {
    const read = readBlocks(fence(gemmaChat, 4))!;
    expect(read.dropped).toEqual([]);
    const stops = (read.blocks[0] as any).groups[0].items;
    expect(stops.map((s: any) => s.title)).toEqual(["Day 1: Nature & Lakes", "Day 2: Views & Heritage", "Day 3: Relaxed Exploration"]);
    expect(stops[0].time).toBeUndefined();
    expect(stops[0].note).toContain("Botanical Gardens");
  });
  it("also takes a group's stops under events", () => {
    const read = readBlocks(JSON.stringify([{ type: "timeline", groups: [{ label: "Day 1", events: [{ time: "09:00", title: "Lake" }] }] }]))!;
    expect(read.dropped).toEqual([]);
    expect((read.blocks[0] as any).groups[0]).toEqual({ label: "Day 1", items: [{ time: "09:00", title: "Lake" }] });
  });
  it("still drops a timeline with nothing to draw, with a note", () => {
    const read = readBlocks(JSON.stringify([{ type: "timeline", title: "Day 3" }]))!;
    expect(read.blocks).toEqual([]);
    expect(read.dropped).toEqual([{ path: "0", why: "timeline needs groups" }]);
  });
});

describe("ranked lists under guessed names (Opus 5.5, Qwen 3.8, Gemma 4)", () => {
  it("draws Opus's \"ranked\" block as a numbered list, its badges as values", () => {
    const read = readBlocks(fence(opusChat, 7))!;
    expect(read.dropped).toEqual([]);
    const list = read.blocks[0] as any;
    expect(list).toMatchObject({ type: "list", ranked: true, title: "Top 5 filter coffee spots in Bangalore ☕" });
    expect(list.items[0]).toEqual({ title: "Brahmin's Coffee Bar", value: "Fan favourite",
      subtitle: "Basavanagudi · LBB says it has a \"roaring lead\" in their polls. Have it with their idli-vada." });
  });
  it("draws Qwen's \"ranked\" block, ignoring each row's rank (the order is the rank)", () => {
    const read = readBlocks(fence(qwenChat, 7))!;
    expect(read.dropped).toEqual([]);
    const list = read.blocks[0] as any;
    expect(list.ranked).toBe(true);
    expect(list.items.map((i: any) => i.title)).toEqual(["Vidyarthi Bhavan", "Central Tiffin Room (CTR)", "Brahmins' Coffee Bar",
      "Nothing Before Coffee", "Namma Filter Coffee"]);
    expect(list.items[0]).not.toHaveProperty("rank");
  });
  it("draws Gemma's \"ranked list\", each row's text as its title and its score as the value", () => {
    const read = readBlocks(fence(gemmaChat, 7))!;
    expect(read.dropped).toEqual([]);
    const list = read.blocks[0] as any;
    expect(list.type).toBe("list");
    expect(list.items[0]).toEqual({
      title: "⭐ **MTR (Mavalli Tiffin Rooms)** - The gold standard for traditional South Indian breakfast and coffee.", value: "5" });
  });
  it("takes \"ranking\" too", () => {
    const read = readBlocks(JSON.stringify([{ type: "ranking", items: [{ name: "A" }] }]))!;
    expect(read.blocks).toEqual([{ type: "list", ranked: true, items: [{ title: "A" }] }]);
  });
});

describe("tiles without titles (Opus 5.5, GLM 5.3)", () => {
  it("draws Opus's weather tiles: the label is the title, value and note go under it", () => {
    const read = readBlocks(fence(opusChat, 9))!;
    expect(read.dropped).toEqual([]);
    const tiles = (read.blocks[0] as any).items;
    expect(tiles).toHaveLength(4);
    expect(tiles[0]).toEqual({ title: "Right now", subtitle: "24°C · overcast · 0 mm rain" });
  });
  it("draws GLM's tiles, listed under `tiles`, each a label and a text", () => {
    const read = readBlocks(fence(glmChat, 15))!;
    expect(read.dropped).toEqual([]);
    expect((read.blocks[0] as any).items[0]).toEqual({ title: "Seat & meal", subtitle: "🪟 Window seat · 🥗 Veg meals on flights" });
  });
  it("still drops a tiles block with no tile to draw, with a note", () => {
    const read = readBlocks(JSON.stringify([{ type: "tiles", items: [{ image: "https://x.example/a.jpg" }] }]))!;
    expect(read.blocks).toEqual([]);
    expect(read.dropped).toEqual([{ path: "0.items.0", why: "tile has no title" }, { path: "0", why: "tiles has no item with a title" }]);
  });
});

describe("JSON slips (Gemma 4)", () => {
  it("draws Gemma's chart whose numbers have thousands commas, and its success callout as a tip", () => {
    const spec = parseChart(fence(gemmaChat, 5, 0))!;
    expect(spec.series[0].data).toEqual([37846000, 27950000]);
    const callout = readBlocks(fence(gemmaChat, 5, 2))!;
    expect(callout.blocks[0]).toMatchObject({ type: "callout", tone: "tip" });
  });
  it("draws Gemma's packing list whose strings were never closed, every item whole", () => {
    const read = readBlocks(fence(gemmaChat, 3))!;
    expect(read.dropped).toEqual([]);
    const items = (read.blocks[0] as any).items;
    expect(items).toHaveLength(7);
    expect(items[0].text).toBe("🧥 Heavy Woolens (Jackets, sweaters, thermal wear - it gets cold!)");
    expect(items[6].text).toBe("🌂 Umbrella or light raincoat (December can have mist/drizzle)");
  });
  it("never changes JSON that already reads", () => {
    const fine = '[{"text": "Total: 1,000, \\"done\\": yes", "data": [12,105,230], "ok": true}, {"n": null}]';
    expect(readJson(fine)).toEqual(JSON.parse(fine));
    expect(closeUnclosedStrings(fine)).toBe(fine);
    expect(joinThousands(fine)).toBe(fine);
  });
  it("joins thousands only outside strings, and only when a group shows it (a group starting with 0)", () => {
    expect(joinThousands('{"t": "₹1,000", "d": [1,000, 2,500]}')).toBe('{"t": "₹1,000", "d": [1000, 2500]}');
    expect(joinThousands('{"d": [12,105,230]}')).toBe('{"d": [12,105,230]}');
  });
  it("leaves JSON cut off mid-stream unread", () => {
    expect(readJson('[{"type": "checklist", "items": [{"text": "Socks (wool), "checked"')).toBeUndefined();
  });
});
