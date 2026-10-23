import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Need } from "../needs";
import { NeedsYou } from "./NeedsYou";

const bill: Need = {
  ref: "task:7", title: "Pay electricity bill ₹2,480", why: "Reminder", icon: "rupee", badge: "Overdue", ask: "Tell me about task #7",
  main: { label: "Done", action: "done_task", value: 7 }, other: { label: "Tomorrow", action: "snooze_task", value: 7 },
};

describe("Needs you on Today", () => {
  it("draws each item as a card with its why, its pill and its two buttons", () => {
    const html = renderToStaticMarkup(<NeedsYou items={[bill]} footer="checked 12:30 · next 13:00" closed={[]} onAct={() => {}} onReopen={() => {}} />);
    expect(html).toContain("Pay electricity bill ₹2,480");
    expect(html).toContain("Overdue");
    expect(html).toContain("chip-warn");
    expect(html).toContain(">Done</button>");
    expect(html).toContain(">Tomorrow</button>");
    expect(html).toContain("checked 12:30 · next 13:00");
  });
  it("folds what the watch closed into one line, and says all clear when nothing needs you", () => {
    const closed = [{ id: 3, title: "Order: desk lamp", why: "delivered", closed: "2026-10-23T08:00:00" }];
    const html = renderToStaticMarkup(<NeedsYou items={[]} footer="" closed={closed} onAct={() => {}} onReopen={() => {}} />);
    expect(html).toContain("All clear.");
    expect(html).toContain("1 done while you were away");
    expect(html).not.toContain("Order: desk lamp");  // folded until tapped
  });
});
