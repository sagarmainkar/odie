import { describe, expect, it, vi } from "vitest";
import { canShareHere, pictureName, shareFile, shareReply, shareText, shareWords, visualsIn, type Sharer } from "./share";

describe("sharing words", () => {
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

describe("sharing a reply with its pictures", () => {
  const piece = (kind: string) => ({ dataset: { visual: kind } }) as unknown as HTMLElement;
  const drawn = async (_p: HTMLElement, _name: string, fileName: string) => ({ file: new File(["png"], fileName, { type: "image/png" }) });
  const undrawn = async () => ({ file: null, why: "the browser gave no picture" });

  it("leaves out small pieces and keeps at most six", () => {
    const bubble = {
      querySelectorAll: () => [40, 200, 300, 120, 500, 95, 90, 800, 150].map((h) => ({ getBoundingClientRect: () => ({ height: h }) })),
    } as unknown as ParentNode;
    expect(visualsIn(bubble, 90).map((p) => p.getBoundingClientRect().height)).toEqual([200, 300, 120, 500, 95, 90]);
    expect(visualsIn(bubble).length).toBe(6);
  });

  it("names each picture after the assistant, in order", () => {
    expect(pictureName("Odie", 0)).toBe("odie-1.png");
    expect(pictureName("  My Odie! ", 2)).toBe("my-odie-3.png");
    expect(pictureName("", 0)).toBe("odie-1.png");
  });

  it("sends the pictures with the words as their caption", async () => {
    const share = vi.fn(async (_data: { files?: File[]; text?: string; title?: string }) => {});
    const went = await shareReply({ text: "Financials dragged.", title: "Odie", visuals: [piece("chart"), piece("table")], name: "Odie" }, drawn, { share, canShare: () => true });
    expect(went).toEqual({ outcome: "shared", pictures: 2 });
    const sent = share.mock.calls[0][0];
    expect(sent.files?.map((f) => f.name)).toEqual(["odie-1.png", "odie-2.png"]);
    expect(sent.text).toBe("Financials dragged.");
  });

  it("falls back to the words, and says why, when a sheet takes no files or nothing could be drawn", async () => {
    const share = vi.fn(async (_data: { files?: File[]; text?: string; title?: string }) => {});
    const noFiles = await shareReply({ text: "Hi", visuals: [piece("chart")], name: "Odie" }, drawn, { share, canShare: () => false });
    expect(noFiles).toEqual({ outcome: "shared", pictures: 0, why: "this browser's sheet can't take files" });
    expect(share.mock.calls[0][0]).toEqual({ text: "Hi", title: undefined });
    const older = await shareReply({ text: "Hi", visuals: [piece("chart")], name: "Odie" }, drawn, { share });  // no canShare: an older sheet
    expect(older.why).toBe("this browser's sheet can't take files");
    const blank = await shareReply({ text: "Hi", visuals: [piece("chart")], name: "Odie" }, undrawn, { share, canShare: () => true });
    expect(blank).toEqual({ outcome: "shared", pictures: 0, why: "the browser gave no picture" });
    const plain = await shareReply({ text: "Hi", visuals: [], name: "Odie" }, drawn, { share, canShare: () => true });
    expect(plain).toEqual({ outcome: "shared", pictures: 0 });
    expect((await shareReply({ text: "Hi", visuals: [], name: "Odie" }, drawn, {})).outcome).toBe("unsupported");
  });
});
