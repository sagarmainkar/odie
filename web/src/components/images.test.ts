import { describe, expect, it } from "vitest";
import { imagesLayout, parseImages } from "./ImageStrip";

describe("parseImages", () => {
  it("reads a odie-images block and drops non-http URLs", () => {
    const s = parseImages('{"title":"Mahabaleshwar","images":[{"url":"https://a/b.jpg","caption":"Venna Lake","source":"wiki"},{"url":"javascript:alert(1)"}]}')!;
    expect(s.title).toBe("Mahabaleshwar"); expect(s.images).toEqual([{ url: "https://a/b.jpg", caption: "Venna Lake", source: "wiki" }]);
  });
  it("accepts a bare list and rejects junk", () => {
    expect(parseImages('["https://a/1.jpg","https://a/2.jpg"]')!.images.length).toBe(2);
    expect(parseImages('{"images":[]}')).toBeNull();
    expect(parseImages("not json")).toBeNull();
  });
});

describe("imagesLayout", () => {
  it("captioned images read as news; bare photos as a mosaic", () => {
    expect(imagesLayout({ images: [{ url: "https://a", caption: "RBI holds" }, { url: "https://b", caption: "Banks rally" }, { url: "https://c" }] })).toBe("news");
    expect(imagesLayout({ images: [{ url: "https://a" }, { url: "https://b" }, { url: "https://c", caption: "x" }] })).toBe("mosaic");
  });
});

describe("parseImages with Odie's own pictures", () => {
  it("accepts a photo's thumbnail address and nothing else relative", () => {
    const s = parseImages('{"images":[{"url":"/api/photos/0F1E2D3C-4B5A-6978-8899-AABBCCDDEEFF/thumb","caption":"16 May 2024 · Goa"},{"url":"/etc/passwd"},{"url":"/api/media/abc"}]}')!;
    expect(s.images.map((i) => i.url)).toEqual(["/api/photos/0F1E2D3C-4B5A-6978-8899-AABBCCDDEEFF/thumb"]);
  });
});

describe("bigUrl", () => {
  it("opens one of Odie's own photos at its big copy, and anything else as it is", async () => {
    const { bigUrl } = await import("./ImageStrip");
    expect(bigUrl("/api/photos/0F1E2D3C-4B5A-6978-8899-AABBCCDDEEFF/thumb")).toBe("/api/photos/0F1E2D3C-4B5A-6978-8899-AABBCCDDEEFF/big");
    expect(bigUrl("https://a/b.jpg")).toBe("https://a/b.jpg");
  });
});
