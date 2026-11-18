import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Need } from "../needs";
import { NeedsYou } from "./NeedsYou";

const bill: Need = {
  ref: "task:7", title: "Pay electricity bill ₹2,480", why: "Reminder", icon: "rupee", badge: "Overdue", ask: "Tell me about task #7",
  main: { label: "Tell me more", action: "chat", value: "Tell me about task #7" }, other: { label: "Done", action: "done_task", value: 7 },
  later: { label: "Later", action: "later", value: "task:7" },
};

describe("Needs you on Pulse", () => {
  it("draws each item as a card with its why, its pill and its three buttons: the move, Done and Later", () => {
    const html = renderToStaticMarkup(<NeedsYou items={[bill]} footer="checked 12:30 · next 13:00" closed={[]} onAct={() => {}} onReopen={() => {}} />);
    expect(html).toContain("Pay electricity bill ₹2,480");
    expect(html).toContain("Overdue");
    expect(html).toContain("chip-warn");
    const buttons = [...html.matchAll(/>(Tell me more|Done|Later)<\/button>/g)].map((m) => m[1]);
    expect(buttons).toEqual(["Tell me more", "Done", "Later"]);
    expect(html).toContain("checked 12:30 · next 13:00");
  });
  it("an older server's card without Later still shows its two buttons", () => {
    const { later: _gone, ...older } = bill;
    const html = renderToStaticMarkup(<NeedsYou items={[older]} footer="" closed={[]} onAct={() => {}} onReopen={() => {}} />);
    expect(html).toContain(">Done</button>");
    expect(html).not.toContain(">Later</button>");
  });
  it("folds what the watch closed into one line, and says all clear when nothing needs you", () => {
    const closed = [{ id: 3, title: "Order: desk lamp", why: "delivered", closed: "2026-10-23T08:00:00" }];
    const html = renderToStaticMarkup(<NeedsYou items={[]} footer="" closed={closed} onAct={() => {}} onReopen={() => {}} />);
    expect(html).toContain("All clear.");
    expect(html).toContain("1 done today");
    expect(html).not.toContain("Order: desk lamp");  // folded until tapped
  });
  it("counts the watch's notes in the same line, each with its files", () => {
    const notes = [{ at: "2026-10-23T10:00:00+05:30", message: "Made the deck from the PDF", media: [{ id: "abc", title: "deck.pptx", filename: "deck.pptx" }] }];
    const html = renderToStaticMarkup(<NeedsYou items={[]} footer="" closed={[]} notes={notes} onAct={() => {}} onReopen={() => {}} open />);
    expect(html).toContain("1 done today");
    expect(html).toContain("Made the deck from the PDF");
    expect(html).toContain('href="/api/media/abc"');
  });
});
