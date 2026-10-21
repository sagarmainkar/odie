// @vitest-environment jsdom
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it } from "vitest";
import { FileCard } from "./FileCard";
import { ShareFile, ShareWords, wordsAloneNote } from "./ShareButton";

const withSheet = (on: boolean) => Object.defineProperty(navigator, "share", { value: on ? async () => {} : undefined, configurable: true });
afterEach(() => withSheet(false));

describe("sharing a reply", () => {
  it("is a share button only where the browser has a sheet, and only for a reply with words", () => {
    expect(renderToStaticMarkup(<ShareWords text="Three colleges offer it." sheet={false} />)).toBe("");
    expect(renderToStaticMarkup(<ShareWords text={"```chart\n{}\n```"} sheet={true} />)).toBe("");  // no words to send
    const mac = renderToStaticMarkup(<ShareWords text="Hi" sheet={true} />);
    expect(mac).toContain('aria-label="Share"');
    expect(mac).not.toContain("whatsapp://");
  });

  it("says when the words went alone, and why", () => {
    expect(wordsAloneNote(2, { outcome: "shared", pictures: 0, why: "the browser gave no picture" })).toBe("Words only: the browser gave no picture");
    expect(wordsAloneNote(2, { outcome: "shared", pictures: 0 })).toBe("Words only: the pictures couldn't be drawn");
    expect(wordsAloneNote(2, { outcome: "shared", pictures: 2 })).toBe("");
    expect(wordsAloneNote(0, { outcome: "shared", pictures: 0 })).toBe("");
    expect(wordsAloneNote(2, { outcome: "cancelled", pictures: 0, why: "x" })).toBe("");
  });
});

describe("sharing a made file", () => {
  const pdf = { id: "m7", kind: "file" as const, title: "Aerospace", mime: "application/pdf", size: 120000, created: 0, filename: "aerospace.pdf" };

  it("is a share button only where the sheet exists", () => {
    expect(renderToStaticMarkup(<ShareFile file={pdf} sheet={false} />)).toBe("");
    expect(renderToStaticMarkup(<ShareFile file={pdf} sheet={true} />)).toContain('aria-label="Share"');
  });

  it("sits on the file card beside the download", () => {
    withSheet(true);
    const card = renderToStaticMarkup(<FileCard m={pdf} />);
    expect(card).toContain('aria-label="Download aerospace.pdf, PDF, 117 KB"');
    expect(card).toContain('aria-label="Share"');
    withSheet(false);
    expect(renderToStaticMarkup(<FileCard m={pdf} />)).not.toContain('aria-label="Share"');
  });
});
