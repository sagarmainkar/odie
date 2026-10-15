import { describe, expect, it } from "vitest";
import { uuidOf, viewFor, type Original } from "./ownPhoto";

describe("uuidOf", () => {
  it("reads the uuid out of one of Odie's own photo addresses, and nothing out of others", () => {
    expect(uuidOf("/api/photos/0F1E2D3C-4B5A-6978-8899-AABBCCDDEEFF/thumb")).toBe("0F1E2D3C-4B5A-6978-8899-AABBCCDDEEFF");
    expect(uuidOf("/api/photos/0F1E2D3C-4B5A-6978-8899-AABBCCDDEEFF/big")).toBe("0F1E2D3C-4B5A-6978-8899-AABBCCDDEEFF");
    expect(uuidOf("https://a/b.jpg")).toBeNull();
  });
});

describe("viewFor: what the large view shows for a video", () => {
  const info = (state: Original["state"], error = "") => ({ kind: "video" as const, original: { state, error } });
  it("offers Play until the file is fetched, says it is fetching, then plays, and shows a failure plainly", () => {
    expect(viewFor(info("missing"))).toEqual({ show: "poster", button: "Play", note: "" });
    expect(viewFor(info("fetching"))).toEqual({ show: "poster", button: null, note: "Fetching from iCloud…" });
    expect(viewFor(info("ready"))).toEqual({ show: "video", button: null, note: "" });
    expect(viewFor(info("failed", "Photos couldn't fetch it"))).toEqual({ show: "poster", button: "Try again", note: "Photos couldn't fetch it" });
  });
  it("shows a photo as its big copy, nothing to fetch", () => {
    expect(viewFor({ kind: "photo", original: { state: "missing", error: "" } })).toEqual({ show: "picture", button: null, note: "" });
  });
});
