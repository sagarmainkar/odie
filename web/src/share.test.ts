import { describe, expect, it, vi } from "vitest";
import { canShareHere, shareFile, shareText, shareWords, whatsappLink, type Sharer } from "./share";

describe("sharing words", () => {
  it("opens WhatsApp with the words ready to send", () => {
    expect(whatsappLink("Three colleges offer it.")).toBe("whatsapp://send?text=Three%20colleges%20offer%20it.");
  });

  it("reads a reply as a chat message: no fences, marks or pictures, links as their words", () => {
    const reply = "## Colleges\n\n- **COEP** — Pune\n- *VIT* Pune\n\n```chart\n{\"kind\": \"bar\"}\n```\n\nSee [the list](https://x.y).\n\n\n![map](/api/media/m1)\nCall `admissions`.";
    expect(shareWords(reply)).toBe("Colleges\n\n- COEP — Pune\n- VIT Pune\n\nSee the list.\n\nCall admissions.");
    expect(shareWords("Plain words.")).toBe("Plain words.");
    expect(shareWords("Cut off\n```chart\n{")).toBe("Cut off");  // a fence still open while streaming
  });

  it("knows whether the sheet exists", () => {
    expect(canShareHere({ share: async () => {} })).toBe(true);
    expect(canShareHere({})).toBe(false);
  });

  it("hands words to the sheet, and says when it was closed", async () => {
    const share = vi.fn(async () => {});
    expect(await shareText("Hi", "Odie", { share })).toBe("shared");
    expect(share).toHaveBeenCalledWith({ title: "Odie", text: "Hi" });
    expect(await shareText("Hi", undefined, { share: async () => { throw new DOMException("closed", "AbortError"); } })).toBe("cancelled");
    expect(await shareText("Hi", undefined, { share: async () => { throw new Error("no"); } })).toBe("failed");
    expect(await shareText("Hi", undefined, {})).toBe("unsupported");
  });
});

describe("sharing a file", () => {
  const pdf = { id: "m7", filename: "aerospace.pdf", title: "Aerospace" };
  const served = (ok = true) => vi.fn(async () => ({ ok, blob: async () => new Blob(["%PDF"], { type: "application/pdf" }) })) as unknown as typeof fetch;

  it("fetches the file and hands it to the sheet under its download name", async () => {
    const share = vi.fn(async (_data: { files?: File[]; title?: string }) => {});
    const nav: Sharer = { share, canShare: () => true };
    expect(await shareFile(pdf, { nav, fetch: served() })).toBe("shared");
    const sent = share.mock.calls[0][0] as { files: File[]; title: string };
    expect(sent.title).toBe("aerospace.pdf");
    expect(sent.files[0].name).toBe("aerospace.pdf");
    expect(sent.files[0].type).toBe("application/pdf");
  });

  it("says what stood in the way", async () => {
    const closed: Sharer = { share: async () => { throw new DOMException("closed", "AbortError"); }, canShare: () => true };
    expect(await shareFile(pdf, { nav: closed, fetch: served() })).toBe("cancelled");
    expect(await shareFile(pdf, { nav: { share: async () => {}, canShare: () => false }, fetch: served() })).toBe("unsupported");
    expect(await shareFile(pdf, { nav: { share: async () => {} }, fetch: served() })).toBe("unsupported");  // no canShare: an older sheet
    expect(await shareFile(pdf, { nav: { share: async () => {}, canShare: () => true }, fetch: served(false) })).toBe("failed");
    const down = vi.fn(async () => { throw new TypeError("Load failed"); }) as unknown as typeof fetch;
    expect(await shareFile(pdf, { nav: { share: async () => {}, canShare: () => true }, fetch: down })).toBe("failed");
  });
});
