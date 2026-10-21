// @vitest-environment jsdom
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { WatchClosed, whyLine } from "./WatchClosed";

describe("what the watch closed", () => {
  it("says why in a line that reads as a sentence", () => {
    expect(whyLine("paid: confirmation mail 21 Oct")).toBe("Paid: confirmation mail 21 Oct");
    expect(whyLine("")).toBe("Closed by Odie");
  });

  it("lists each one, done, with a way to reopen it", () => {
    const html = renderToStaticMarkup(<WatchClosed items={[{ id: 27, title: "Pay electricity bill — ₹4,280",
      why: "paid: confirmation mail 21 Oct", closed: "2026-10-21T10:00:00.000Z" }]} onReopen={() => {}} />);
    expect(html).toContain("Pay electricity bill — ₹4,280");
    expect(html).toContain("Paid: confirmation mail 21 Oct");
    expect(html).toContain("Reopen");
  });

  it("is nothing when the watch closed nothing", () => {
    expect(renderToStaticMarkup(<WatchClosed items={[]} onReopen={() => {}} />)).toBe("");
  });
});
