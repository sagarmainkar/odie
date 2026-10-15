import { renderToStaticMarkup } from "react-dom/server";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { describe, expect, it } from "vitest";
import { Blocks } from "./Blocks";
import { fenceAsText } from "./fenceText";
import { MarkdownSpan } from "./InlineText";
import { remarkInline } from "./inlineSyntax";
import { parseBlocks } from "./parse";

function draw(json: unknown): string {
  const code = JSON.stringify(json);
  return renderToStaticMarkup(<Blocks blocks={parseBlocks(code)!} source={code} />);
}

describe("a fence with nothing drawable", () => {
  it("says it couldn't draw, with a way to read it as text (not an empty box)", () => {
    const code = '[{"type":"weather","city":"Ooty"}]';
    const html = renderToStaticMarkup(<Blocks blocks={parseBlocks(code)!} source={code} />);
    expect(html).toContain("Couldn’t draw this");
    expect(html).toContain("Show as text");
  });
  it("reads as plain lines when shown as text", () => {
    const code = JSON.stringify([{ type: "timeline", title: "Kyoto", groups: [{ label: "Day 1", items: [{ time: "09:00", title: "Fushimi Inari", icon: "walk" }] }] }]);
    expect(fenceAsText(code)).toBe("Kyoto\nDay 1\n09:00 · Fushimi Inari");
    expect(fenceAsText("[{broken")).toBe("[{broken");
  });
});

describe("drawing the new blocks", () => {
  it("draws a table that scrolls inside its card, with the best row badged and inline badges drawn", () => {
    const html = draw([{ type: "table", columns: ["Phone", "Price", "Camera"],
      rows: [["Pixel", "₹44,999", ":badge[Top]{good}"], ["Galaxy", "₹42,999", "Good"]], highlight: { row: 0 } }]);
    expect(html).toContain("overflow-x-auto");
    expect(html).toContain(">Best<");
    expect(html).toContain('class="chip chip-inline chip-good">Top<');
    expect(html).not.toContain(":badge");
  });
  it("draws a ranked list with numbers, and a section that drops the inner card", () => {
    const html = draw([{ type: "section", title: "Cafés", children: [{ type: "list", ranked: true, items: ["Third Wave", "Dyu"] }] }]);
    expect(html).toContain(">1<");
    expect(html).toContain(">2<");
    expect(html.match(/glass glass-solid/g)?.length).toBe(1);  // only the section's card
  });
  it("draws a collapsed section closed, title showing", () => {
    const html = draw([{ type: "section", title: "Packing", collapsed: true, children: [{ type: "text", text: "Hidden until tapped" }] }]);
    expect(html).toContain("Packing");
    expect(html).toContain('aria-expanded="false"');
    expect(html).not.toContain("Hidden until tapped");
  });
  it("draws every atom without throwing", () => {
    const html = draw([{ type: "row", children: [{ type: "stat", label: "Saved", value: 4200, unit: "₹" }, { type: "badge", text: "New" }] },
      { type: "grid", children: [{ type: "bar", label: "Packed", value: 6, max: 9 }, { type: "image", url: "https://x.example/a.jpg" }] },
      { type: "heading", text: "Next" }, { type: "text", text: "**Go** early :icon[sun]" }, { type: "divider" },
      { type: "button", label: "Book", url: "https://example.com" }, { type: "link", url: "https://example.com" },
      { type: "callout", tone: "warn", text: "Carry cash" }]);
    expect(html).toContain("₹4,200");
    expect(html).toContain("6 / 9");
    expect(draw([{ type: "bar", label: "Food", value: 7200, max: 8000, unit: "₹" }])).toContain("₹7,200 / ₹8,000");
    expect(draw([{ type: "bar", label: "Budget", value: 62 }])).toContain("62%");
    expect(html).toContain("<b class=\"font-bold\">Go</b>");
  });
});

describe("inline badges and icons in reply Markdown", () => {
  function md(text: string): string {
    return renderToStaticMarkup(<ReactMarkdown remarkPlugins={[remarkGfm, remarkInline]} components={{ span: MarkdownSpan }}>{text}</ReactMarkdown>);
  }
  it("draws a badge and an icon in a sentence", () => {
    const html = md("Take the :icon[plane] flight :badge[Cheapest]{good} today.");
    expect(html).toContain('<span class="chip chip-inline chip-good">Cheapest</span>');
    expect(html).toContain('<span class="inline-icon"><svg');
    expect(html).not.toContain(":icon");
  });
  it("works inside a Markdown table cell and leaves code alone", () => {
    const html = md("| Phone | Note |\n|---|---|\n| Pixel | :badge[Best] |\n\n`:badge[x]`");
    expect(html).toContain('<span class="chip chip-inline chip-soft">Best</span>');
    expect(html).toContain("<code>:badge[x]</code>");
  });
  it("drops an unknown icon and keeps the words", () => {
    expect(md("Go :icon[rocket] now")).toBe("<p>Go  now</p>");
  });
});

describe("drawing a checklist", () => {
  it("shows how many are done, ticks the model's done items, numbers and groups", () => {
    const html = draw([{ type: "checklist", title: "Ooty", numbered: true, items: [
      { text: "Jacket", group: "Clothes", done: true }, { text: "Socks", group: "Clothes" }, { text: "Passport", group: "Papers" }] }]);
    expect(html).toContain("1 of 3 done");
    expect(html.match(/role="checkbox"/g)?.length).toBe(3);
    expect(html.match(/aria-checked="true"/g)?.length).toBe(1);
    expect(html).toContain(">Clothes<");
    expect(html).toContain(">Papers<");
    expect(html).toContain(">2<");  // the second item's number
  });
  it("says all done when every item is ticked", () => {
    expect(draw([{ type: "checklist", items: [{ text: "Tickets", done: true }] }])).toContain("All done");
  });
});

describe("drawing a calculator and shared values", () => {
  const calculator = { type: "calculator", title: "Home loan",
    inputs: [{ id: "p", label: "Loan", min: 1000000, max: 10000000, step: 100000, value: 4000000, unit: "₹" },
      { id: "r", label: "Rate", min: 6, max: 12, step: 0.1, value: 8.5, unit: "%" },
      { id: "n", label: "Years", min: 5, max: 30, step: 1, value: 20, unit: "years" }],
    outputs: [{ label: "Monthly EMI", formula: "emi(p, r, n)", unit: "₹" }, { label: "Broken", formula: "p / (n - 20)", unit: "₹" }] };
  it("draws a slider per input and works out each result (– for one that can't be)", () => {
    const html = draw([calculator]);
    expect(html.match(/type="range"/g)?.length).toBe(3);
    expect(html).toContain("₹40,00,000");
    expect(html).toContain("8.5%");
    expect(html).toContain("20 years");
    expect(html).toContain(">₹34,713<");
    expect(html).toContain(">–<");
  });
  it("fills {formula} in other blocks of the same fence, inside containers too", () => {
    const html = draw([calculator, { type: "section", title: "Over {n} years", children: [
      { type: "text", text: "You pay **₹{round(emi(p, r, n) * n * 12)}** in all" },
      { type: "stat", label: "Interest", value: "₹{round(emi(p, r, n) * n * 12 - p)}" }] }]);
    expect(html).toContain("Over 20 years");
    expect(html).toContain("<b class=\"font-bold\">₹83,31,103</b>");
    expect(html).toContain("₹43,31,103");
  });
  it("leaves braces alone in a fence without a calculator", () => {
    expect(draw([{ type: "text", text: "Use {p} here" }])).toContain("Use {p} here");
  });
});
