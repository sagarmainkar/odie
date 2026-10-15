import { describe, expect, it } from "vitest";
import { formatAmount, formatChange, parseBlocks } from "./parse";

describe("parseBlocks", () => {
  it("reads chart, kpis, actions and source; skips unknown kinds", () => {
    const b = parseBlocks(JSON.stringify([
      { type: "chart", kind: "bar", title: "Rev", x: ["Q1", "Q2"], series: [{ name: "R", data: [1, 2] }], unit: "$M" },
      { type: "kpis", items: [{ label: "Revenue", value: 182.2, unit: "$M", change: 3.8, change_unit: "%" }] },
      { type: "weather", foo: 1 },
      { type: "actions", items: [{ label: "Analyze", run: "Analyze Qualys: last 4 quarters" }, { label: "" }] },
      { type: "source", text: "SEC filings", url: "https://www.sec.gov/x" },
    ]))!;
    expect(b.map((x) => x.type)).toEqual(["chart", "kpis", "actions", "source"]);
    expect(b[0].type === "chart" && b[0].spec.type).toBe("bar");
    expect(b[2].type === "actions" && b[2].items.length).toBe(1);
  });
  it("returns null for broken JSON or a non-list", () => {
    expect(parseBlocks("[{")).toBeNull();
    expect(parseBlocks('"just text"')).toBeNull();
    expect(parseBlocks('{"type":"kpis"}')).toEqual([]);  // a lone block is accepted; this one has nothing to draw
  });
  it("drops non-http source links", () => {
    const b = parseBlocks(JSON.stringify([{ type: "source", text: "x", url: "javascript:alert(1)" }]))!;
    expect(b[0].type === "source" && b[0].url).toBeUndefined();
  });
});

describe("formatChange", () => {
  it("shows direction and unit", () => {
    expect(formatChange(3.84, "%")).toBe("▲ 3.8%");
    expect(formatChange(-0.4, "pt")).toBe("▼ 0.4 pt");
    expect(formatChange(0, "%")).toBe("0.0%");
    expect(formatChange(null)).toBe("");
  });
});

describe("formatAmount", () => {
  it("writes currency + scale units", () => {
    expect(formatAmount(294059, "₹Cr")).toBe("₹2,94,059 Cr");
    expect(formatAmount(109417, "$M")).toBe("$109,417M");
    expect(formatAmount(812.4, "€M")).toBe("€812.4M");
    expect(formatAmount(-15342, "₹Cr")).toBe("-₹15,342 Cr");
    expect(formatAmount(36.9, "₹")).toBe("₹36.9");
  });
  it("leaves other units alone", () => {
    expect(formatAmount(34, "%")).toBeNull();
    expect(formatAmount(12, "pts")).toBeNull();
    expect(formatAmount(12, undefined)).toBeNull();
  });
});

describe("new blocks", () => {
  it("reads tiles: https images only, tap runs or asks, at most 8", () => {
    const b = parseBlocks(JSON.stringify([{ type: "tiles", items: [
      { title: "Sleep", subtitle: "Wake up refreshed", image: "https://x.example/a.jpg", icon: "moon", ask: "Help me sleep better" },
      { title: "Kyoto", image: "javascript:alert(1)", icon: "nope", run: "Plan Kyoto" },
      { subtitle: "no title" },
      ...Array.from({ length: 9 }, (_, i) => ({ title: `T${i}` })),
    ] }]))!;
    expect(b[0].type).toBe("tiles");
    const items = (b[0] as any).items;
    expect(items.length).toBe(8);
    expect(items[0]).toMatchObject({ title: "Sleep", image: "https://x.example/a.jpg", icon: "moon", ask: "Help me sleep better" });
    expect(items[1].image).toBeUndefined();
    expect(items[1].icon).toBeUndefined();
    expect(items[1].run).toBe("Plan Kyoto");
  });
  it("reads progress with checkpoints in order and clamps nothing silly", () => {
    const b = parseBlocks(JSON.stringify([{ type: "progress", title: "Level 4", value: 95, goal: 120, unit: "XP",
      steps: [{ label: "90 XP", at: 90 }, { label: "30 XP", at: 30 }, { label: "bad" }] }]))!;
    expect(b[0]).toMatchObject({ type: "progress", title: "Level 4", value: 95, goal: 120, unit: "XP" });
    expect((b[0] as any).steps.map((s: any) => s.at)).toEqual([30, 90]);
    expect(parseBlocks(JSON.stringify([{ type: "progress", title: "x", value: 5, goal: 0 }]))).toEqual([]);
  });
  it("reads a streak: count plus up to 7 days", () => {
    const b = parseBlocks(JSON.stringify([{ type: "streak", count: 3, label: "Current streak", unit: "days",
      days: [{ label: "Mon", done: true }, { label: "Thu", date: "12", today: true }, ...Array.from({ length: 8 }, () => ({ label: "x" }))] }]))!;
    const s = b[0] as any;
    expect(s.count).toBe(3);
    expect(s.days.length).toBe(7);
    expect(s.days[1]).toEqual({ label: "Thu", date: "12", done: false, today: true });
  });
  it("reads a timeline grouped by day", () => {
    const b = parseBlocks(JSON.stringify([{ type: "timeline", title: "Kyoto, 3 days", groups: [
      { label: "Day 1 · Fri 9 Oct", items: [{ time: "09:00", title: "Fushimi Inari", place: "Fushimi", icon: "walk", note: "Go early" }, { note: "no title" }] },
      { label: "empty", items: [] },
    ] }]))!;
    const t = b[0] as any;
    expect(t.groups.length).toBe(1);
    expect(t.groups[0].items).toEqual([{ time: "09:00", title: "Fushimi Inari", place: "Fushimi", icon: "walk", note: "Go early" }]);
  });
});

describe("forgiving shapes (what models actually write)", () => {
  it("takes a single block object, not only a list", () => {
    const b = parseBlocks(JSON.stringify({ type: "progress", title: "Trip", value: 1, goal: 4 }))!;
    expect(b.map((x) => x.type)).toEqual(["progress"]);
  });
  it("takes actions as buttons and a source as a list of sources", () => {
    const b = parseBlocks(JSON.stringify([
      { type: "actions", title: "Next", buttons: [{ label: "Book camp", ask: "Find desert camps in Sam" }, { text: "Weather", run: "Jaisalmer weather this week" }] },
      { type: "source", title: "Sources", sources: [{ name: "ixigo", url: "https://www.ixigo.com/x" }, { name: "Wikipedia" }] },
    ]))!;
    expect(b[0]).toEqual({ type: "actions", items: [{ label: "Book camp", run: "Find desert camps in Sam" }, { label: "Weather", run: "Jaisalmer weather this week" }] });
    expect(b[1]).toEqual({ type: "source", text: "ixigo · Wikipedia", url: "https://www.ixigo.com/x" });
  });
});

describe("kpis with text values", () => {
  it("keeps short text values (trackers report facts, not only numbers)", () => {
    const b = parseBlocks(JSON.stringify([{ type: "kpis", items: [{ label: "Opponent", value: "Leeds United (H)" }, { label: "Goals", value: 2 }] }]))!;
    expect((b[0] as any).items.map((i: any) => i.value)).toEqual(["Leeds United (H)", 2]);
  });
});

describe("LaTeX symbols in block text", () => {
  it("draws arrows, not code", () => {
    const out = parseBlocks(JSON.stringify([{ type: "timeline", groups: [{ label: "Day 1", items: [{ title: "Pune $\\rightarrow$ Goa", note: "Bus $\\\\rightarrow$ ferry" }] }] }]));
    const item = (out![0] as any).groups[0].items[0];
    expect(item.title).toBe("Pune → Goa");
    expect(item.note).toBe("Bus → ferry");
  });
});
