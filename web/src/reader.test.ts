import { describe, expect, it } from "vitest";
import { opensInReader, readerError, readerFormat } from "./reader";

describe("the report reader", () => {
  it("formats Markdown and shows plain text as written", () => {
    expect(readerFormat("AI chips.md")).toBe("markdown");
    expect(readerFormat("notes.MARKDOWN")).toBe("markdown");
    expect(readerFormat("list.txt")).toBe("plain");
    expect(readerFormat("notes.TXT")).toBe("plain");
  });

  it("leaves every other file a download", () => {
    expect(readerFormat("deck.pptx")).toBeNull();
    expect(readerFormat("budget.csv")).toBeNull();
    expect(readerFormat("README")).toBeNull();
    expect(readerFormat("archive.md.zip")).toBeNull();
    expect(opensInReader("report.pdf")).toBe(false);
    expect(opensInReader("page.html")).toBe(false);
  });

  it("opens Markdown and text files", () => {
    expect(opensInReader("Research on local models.md")).toBe(true);
    expect(opensInReader("list.txt")).toBe(true);
  });

  it("says why a file couldn't be opened", () => {
    expect(readerError(404)).toBe("This file isn't on Odie any more.");
    expect(readerError(500)).toBe("Couldn't open the file (HTTP 500). Try again.");
  });
});
