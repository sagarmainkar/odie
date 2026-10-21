// @vitest-environment jsdom
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it } from "vitest";
import { FileCard } from "./FileCard";
import { ShareFile, ShareWords } from "./ShareButton";

const withSheet = (on: boolean) => Object.defineProperty(navigator, "share", { value: on ? async () => {} : undefined, configurable: true });
afterEach(() => withSheet(false));

describe("sharing a reply", () => {
  it("shows nothing where the browser can neither share nor open WhatsApp", () => {
    expect(renderToStaticMarkup(<ShareWords text="Three colleges offer it." sheet={false} phone={false} />)).toBe("");
    expect(renderToStaticMarkup(<ShareWords text={"```chart\n{}\n```"} sheet={true} phone={true} />)).toBe("");  // no words to send
  });

  it("opens WhatsApp with the reply's words on a phone, and the sheet where there is one", () => {
    const phone = renderToStaticMarkup(<ShareWords text={"## Colleges\n\n**COEP** — Pune"} sheet={false} phone={true} />);
    expect(phone).toContain('href="whatsapp://send?text=Colleges%0A%0ACOEP%20%E2%80%94%20Pune"');
    expect(phone).toContain("WhatsApp");
    expect(phone).not.toContain('aria-label="Share"');
    const mac = renderToStaticMarkup(<ShareWords text="Hi" sheet={true} phone={false} />);
    expect(mac).toContain('aria-label="Share"');
    expect(mac).not.toContain("whatsapp://");
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
