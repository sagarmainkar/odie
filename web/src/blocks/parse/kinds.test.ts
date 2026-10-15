// The new ready-made blocks and atoms: for each, a good input, a sloppy one written the way models write, and a broken
// one that is dropped with a note saying why.
import { describe, expect, it } from "vitest";
import { readBlocks } from "../parse";

/** Parse one block object; returns what was drawn and what was dropped. */
function one(block: unknown) {
  return readBlocks(JSON.stringify([block]))!;
}

describe("callout", () => {
  it("reads a tip with a title", () => {
    expect(one({ type: "callout", tone: "tip", title: "Go early", text: "Gates open at 6." }).blocks).toEqual([
      { type: "callout", tone: "tip", title: "Go early", text: "Gates open at 6." }]);
  });
  it("takes variant/body aliases and maps warning → warn; a lone title becomes the text", () => {
    expect(one({ type: "callout", variant: "Warning", body: "Carry cash." }).blocks).toEqual([{ type: "callout", tone: "warn", text: "Carry cash." }]);
    expect(one({ type: "callout", tone: "purple", title: "Just this" }).blocks).toEqual([{ type: "callout", tone: "info", text: "Just this" }]);
  });
  it("drops a callout with nothing to say", () => {
    const r = one({ type: "callout", tone: "warn" });
    expect(r.blocks).toEqual([]);
    expect(r.dropped).toEqual([{ path: "0", why: "callout needs text" }]);
  });
});

describe("table", () => {
  it("reads columns, rows, a highlighted row and a caption", () => {
    const r = one({ type: "table", caption: "Under ₹50k", columns: ["Phone", "Price"],
      rows: [["Pixel 10a", "₹44,999"], ["Galaxy A76", "₹42,999"]], highlight: { row: 0 } });
    expect(r.blocks).toEqual([{ type: "table", caption: "Under ₹50k", columns: ["Phone", "Price"],
      rows: [["Pixel 10a", "₹44,999"], ["Galaxy A76", "₹42,999"]], highlight: { row: 0 } }]);
    expect(r.dropped).toEqual([]);
  });
  it("takes headers/data, object rows keyed by column name, numbers, short rows and a bare-number highlight", () => {
    const r = one({ type: "table", title: "Phones", headers: ["Phone", { label: "Price" }, "5G"],
      data: [["Pixel", 44999, true], { phone: "Galaxy", Price: "₹42,999" }, ["Nothing"]], highlight: 1 });
    expect(r.blocks[0]).toEqual({ type: "table", caption: "Phones", columns: ["Phone", "Price", "5G"],
      rows: [["Pixel", "44999", "Yes"], ["Galaxy", "₹42,999", ""], ["Nothing", "", ""]], highlight: { row: 1 } });
  });
  it("takes column names from the first row when there are no columns", () => {
    expect((one({ type: "table", rows: [["City", "Temp"], ["Ooty", "18°"]] }).blocks[0] as any).columns).toEqual(["City", "Temp"]);
    expect((one({ type: "table", rows: [{ City: "Ooty", Temp: "18°" }] }).blocks[0] as any)).toMatchObject({ columns: ["City", "Temp"], rows: [["Ooty", "18°"]] });
  });
  it("picks the highlight by name: a row's first cell or a column", () => {
    const rows = [["Pixel 10a", "1"], ["Nothing 4", "2"]];
    expect((one({ type: "table", columns: ["Phone", "Rank"], rows, highlight: "Nothing 4" }).blocks[0] as any).highlight).toEqual({ row: 1 });
    expect((one({ type: "table", columns: ["Phone", "Rank"], rows, highlight: { col: 1 } }).blocks[0] as any).highlight).toEqual({ column: 1 });
  });
  it("drops a row with too many cells and an out-of-range highlight, with notes", () => {
    const r = one({ type: "table", columns: ["A", "B"], rows: [["1", "2"], ["1", "2", "3"]], highlight: { row: 5 } });
    expect((r.blocks[0] as any).rows).toEqual([["1", "2"]]);
    expect((r.blocks[0] as any).highlight).toBeUndefined();
    expect(r.dropped).toEqual([
      { path: "0.rows.1", why: "row has 3 cells, table has 2 columns" },
      { path: "0.highlight", why: "highlight is outside the table" },
    ]);
  });
  it("drops a table with no rows", () => {
    const r = one({ type: "table", columns: ["A"], rows: [] });
    expect(r.blocks).toEqual([]);
    expect(r.dropped).toEqual([{ path: "0", why: "table has no rows" }]);
  });
});

describe("list", () => {
  it("reads rich rows, ranked, with run and url", () => {
    const r = one({ type: "list", title: "Cafés", ranked: true, items: [
      { title: "Third Wave", subtitle: "Koramangala 5th Block", value: "4.5", icon: "food", run: "Directions to Third Wave" },
      { title: "Dyu Art Café", image: "https://x.example/dyu.jpg", url: "https://dyu.example" }] });
    expect(r.blocks).toEqual([{ type: "list", title: "Cafés", ranked: true, items: [
      { title: "Third Wave", subtitle: "Koramangala 5th Block", value: "4.5", icon: "food", run: "Directions to Third Wave" },
      { title: "Dyu Art Café", image: "https://x.example/dyu.jpg", url: "https://dyu.example" }] }]);
  });
  it("takes strings, name/description/rating aliases, numbered, and refuses unsafe links", () => {
    const r = one({ type: "list", numbered: true, items: ["Matamaal", { name: "Dyu", description: "Garden seats", rating: 4.6, url: "javascript:x", icon: "nope" }] });
    expect(r.blocks).toEqual([{ type: "list", ranked: true, items: [{ title: "Matamaal" }, { title: "Dyu", subtitle: "Garden seats", value: "4.6" }] }]);
  });
  it("drops rows without a title, and a list with none left", () => {
    const r = one({ type: "list", items: [{ subtitle: "no title" }] });
    expect(r.blocks).toEqual([]);
    expect(r.dropped).toEqual([{ path: "0.items.0", why: "row has no title" }, { path: "0", why: "list has no row with a title" }]);
  });
});

describe("atoms", () => {
  it("reads each atom from its canonical fields", () => {
    const r = readBlocks(JSON.stringify([
      { type: "heading", text: "Day 1" },
      { type: "text", text: "Best before 9am :icon[sun]" },
      { type: "badge", text: "New", tone: "good" },
      { type: "button", label: "Book", run: "Book the 9am slot" },
      { type: "link", text: "IRCTC", url: "https://www.irctc.co.in" },
      { type: "image", url: "https://x.example/a.jpg", caption: "Ooty lake" },
      { type: "stat", label: "Saved", value: 42000, unit: "₹", change: 12 },
      { type: "bar", label: "Packed", value: 6, max: 9, unit: "items" },
      { type: "divider" },
    ]))!;
    expect(r.dropped).toEqual([]);
    expect(r.blocks).toEqual([
      { type: "heading", text: "Day 1" },
      { type: "text", text: "Best before 9am :icon[sun]" },
      { type: "badge", text: "New", tone: "good" },
      { type: "button", label: "Book", run: "Book the 9am slot" },
      { type: "link", text: "IRCTC", url: "https://www.irctc.co.in" },
      { type: "image", url: "https://x.example/a.jpg", caption: "Ooty lake" },
      { type: "stat", label: "Saved", value: 42000, unit: "₹", change: 12, change_unit: "%" },
      { type: "bar", label: "Packed", value: 6, max: 9, unit: "items" },
      { type: "divider" },
    ]);
  });
  it("takes the aliases models write", () => {
    const r = readBlocks(JSON.stringify([
      { type: "heading", title: "Day 2" },
      { type: "text", content: "Hello" },
      { type: "badge", label: "Sold out", tone: "warning" },
      { type: "button", text: "Open", url: "https://example.com" },
      { type: "link", url: "https://www.irctc.co.in/nget" },
      { type: "image", src: "https://x.example/b.jpg", alt: "Tea gardens" },
      { type: "stat", title: "Steps", value: "8.2k" },
      { type: "bar", title: "Budget used", value: 62 },
    ]))!;
    expect(r.blocks).toEqual([
      { type: "heading", text: "Day 2" },
      { type: "text", text: "Hello" },
      { type: "badge", text: "Sold out", tone: "warn" },
      { type: "button", label: "Open", url: "https://example.com" },
      { type: "link", text: "irctc.co.in", url: "https://www.irctc.co.in/nget" },
      { type: "image", url: "https://x.example/b.jpg", caption: "Tea gardens" },
      { type: "stat", label: "Steps", value: "8.2k", change: null, change_unit: "%" },
      { type: "bar", label: "Budget used", value: 62, max: 100 },
    ]);
  });
  it("drops broken atoms, each with a note", () => {
    const r = readBlocks(JSON.stringify([
      { type: "heading" }, { type: "badge" }, { type: "button", label: "Go", url: "http://insecure.example" },
      { type: "link", url: "javascript:alert(1)" }, { type: "image", url: "data:x" }, { type: "stat", value: 3 }, { type: "bar", label: "x" },
    ]))!;
    expect(r.blocks).toEqual([]);
    expect(r.dropped.map((d) => d.why)).toEqual([
      "heading needs text", "badge needs text", "button needs run or an https url", "link needs an https url",
      "image needs an https url", "stat needs a label", "bar needs a numeric value",
    ]);
  });
});

describe("checklist", () => {
  it("reads a title, numbered items and groups, and remembers its place in the fence", () => {
    const r = one({ type: "checklist", title: "Ooty", numbered: true,
      items: [{ text: "Jacket", group: "Clothes" }, { text: "Passport", group: "Papers" }] });
    expect(r.blocks).toEqual([{ type: "checklist", title: "Ooty", numbered: true, ticked: [], path: "0",
      items: [{ text: "Jacket", group: "Clothes" }, { text: "Passport", group: "Papers" }] }]);
    expect(r.dropped).toEqual([]);
  });
  it("takes plain strings, tasks/steps, title/label aliases, done items and groups of items", () => {
    expect(one({ type: "checklist", tasks: ["Book cab", { title: "Pay rent", done: true }], ordered: true }).blocks[0]).toEqual(
      { type: "checklist", numbered: true, ticked: [1], path: "0", items: [{ text: "Book cab" }, { text: "Pay rent" }] });
    expect(one({ type: "checklist", label: "Packing", groups: [{ title: "Clothes", items: ["Jacket", { label: "Socks", checked: true }] }] }).blocks[0]).toEqual(
      { type: "checklist", title: "Packing", numbered: false, ticked: [1], path: "0",
        items: [{ text: "Jacket", group: "Clothes" }, { text: "Socks", group: "Clothes" }] });
  });
  it("knows its path inside a container", () => {
    const r = readBlocks(JSON.stringify([{ type: "text", text: "Hi" }, { type: "section", title: "Trip", children: [{ type: "badge", text: "New" }, { type: "checklist", items: ["Tickets"] }] }]))!;
    const section = r.blocks[1] as any;
    expect(section.children[1]).toMatchObject({ type: "checklist", path: "1.children.1" });
  });
  it("drops items without text and keeps 40, with notes", () => {
    const r = one({ type: "checklist", items: ["Ok", { done: true }, 7, ...Array.from({ length: 41 }, (_, i) => `Item ${i}`)] });
    expect((r.blocks[0] as any).items.length).toBe(40);
    expect(r.dropped).toEqual([
      { path: "0.items.1", why: "item has no text" },
      { path: "0.items.2", why: "item has no text" },
      { path: "0", why: "kept the first 40 items of 42" },
    ]);
  });
  it("drops a checklist with nothing to tick", () => {
    const r = one({ type: "checklist", title: "Empty", items: [] });
    expect(r.blocks).toEqual([]);
    expect(r.dropped).toEqual([{ path: "0", why: "checklist has no item with text" }]);
  });
});

describe("calculator", () => {
  const loan = { type: "calculator", title: "Home loan",
    inputs: [{ id: "p", label: "Loan", min: 1000000, max: 10000000, step: 100000, value: 4000000, unit: "₹" },
      { id: "r", label: "Rate", min: 6, max: 12, step: 0.1, value: 8.5, unit: "%" }],
    outputs: [{ label: "EMI", formula: "emi(p, r, 20)", unit: "₹" }] };
  it("reads inputs and outputs as written", () => {
    const r = one(loan);
    expect(r.blocks).toEqual([loan]);
    expect(r.dropped).toEqual([]);
  });
  it("takes sliders/results, name/title/default/expr aliases, and fills in min, max and step", () => {
    const r = one({ type: "calculator", sliders: [{ name: "p", title: "Loan", max: 10000000, default: 4000000, unit: "₹" }, { id: "tip", value: 12 }],
      results: [{ label: "EMI", expr: "emi(p, 8.5, 20)", unit: "₹" }] });
    expect(r.blocks[0]).toEqual({ type: "calculator",
      inputs: [{ id: "p", label: "Loan", min: 0, max: 10000000, step: 100000, value: 4000000, unit: "₹" },
        { id: "tip", label: "tip", min: 0, max: 24, step: 0.2, value: 12 }],
      outputs: [{ label: "EMI", formula: "emi(p, 8.5, 20)", unit: "₹" }] });
  });
  it("keeps a value inside its range", () => {
    const input = (one({ type: "calculator", inputs: [{ id: "x", min: 0, max: 10, value: 50 }] }).blocks[0] as any).inputs[0];
    expect(input.value).toBe(10);
  });
  it("drops bad inputs and outputs with notes; keeps an unreadable formula (it shows –) with a note", () => {
    const r = one({ type: "calculator",
      inputs: [{ id: "p", value: 5 }, { id: "p", value: 6 }, { id: "emi", value: 1 }, { id: "a.b", value: 1 }, { id: "x", min: 5, max: 5 }, "nope"],
      outputs: [{ label: "Half", formula: "p / 2" }, { label: "Bad", formula: "p.constructor" }, { label: "Ghost", formula: "q * 2" }, { label: "Empty" }] });
    expect((r.blocks[0] as any).inputs.map((x: any) => x.id)).toEqual(["p"]);
    expect((r.blocks[0] as any).outputs.map((x: any) => x.label)).toEqual(["Half", "Bad", "Ghost"]);
    expect(r.dropped).toEqual([
      { path: "0.inputs.1", why: 'input id "p" is used twice' },
      { path: "0.inputs.2", why: 'input needs an id like "p" or "rate" (got "emi")' },
      { path: "0.inputs.3", why: 'input needs an id like "p" or "rate" (got "a.b")' },
      { path: "0.inputs.4", why: "input's max must be above its min" },
      { path: "0.inputs.5", why: "input is not an object" },
      { path: "0.outputs.1", why: 'formula can\'t be read (can\'t read ".constructor"); shows –' },
      { path: "0.outputs.2", why: "formula uses q, which no input has; shows –" },
      { path: "0.outputs.3", why: "output needs a label and a formula" },
    ]);
  });
  it("drops a calculator with no usable input", () => {
    const r = one({ type: "calculator", outputs: [{ label: "Two", formula: "1 + 1" }] });
    expect(r.blocks).toEqual([]);
    expect(r.dropped).toEqual([{ path: "0", why: "calculator has no usable input" }]);
  });
});
