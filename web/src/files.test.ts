import { describe, expect, it } from "vitest";
import { kindOf, size, typeLabel } from "./files";

describe("files", () => {
  it("says how big a file is", () => {
    expect(size(820)).toBe("820 B");
    expect(size(14 * 1024)).toBe("14 KB");
    expect(size(2.3 * 1024 * 1024)).toBe("2.3 MB");
  });

  it("knows a file's kind by its name", () => {
    expect(kindOf("Deck.pptx")).toBe("slides");
    expect(kindOf("Trip plan.DOCX")).toBe("doc");
    expect(kindOf("packing list.csv")).toBe("sheet");
    expect(kindOf("budget.xlsx")).toBe("sheet");
    expect(kindOf("page.html")).toBe("web");
    expect(kindOf("lunch.ics")).toBe("calendar");
    expect(kindOf("data.json")).toBe("data");
    expect(kindOf("notes.md")).toBe("text");
    expect(kindOf("archive")).toBe("other");
    expect(typeLabel("slides")).toBe("PowerPoint");
    expect(typeLabel("calendar")).toBe("Calendar event");
  });

  it("calls a PDF a PDF", () => {
    expect(kindOf("Meghalaya Trip Guide.pdf")).toBe("pdf");
    expect(typeLabel(kindOf("Meghalaya Trip Guide.pdf"))).toBe("PDF");
  });
});

describe("pictures, videos and audio files", () => {
  it("are their own kinds with plain labels", async () => {
    const { kindOf, typeLabel } = await import("./files");
    expect(kindOf("logo.svg")).toBe("picture");
    expect(kindOf("clip.MP4")).toBe("video");
    expect(kindOf("tune.m4a")).toBe("audio");
    expect(typeLabel("picture")).toBe("Picture");
    expect(typeLabel("video")).toBe("Video");
  });
});
