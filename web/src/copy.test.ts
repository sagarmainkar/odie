import { describe, expect, it } from "vitest";
import { copyText } from "./copy";

describe("copyText", () => {
  it("uses the clipboard when the browser gives one", async () => {
    let got = "";
    expect(await copyText("hi", { clipboard: { writeText: async (t: string) => { got = t; } }, fallback: () => false })).toBe(true);
    expect(got).toBe("hi");
  });

  it("falls back when there's no clipboard (a page that isn't https or localhost)", async () => {
    let got = "";
    expect(await copyText("hi", { clipboard: undefined, fallback: (t) => { got = t; return true; } })).toBe(true);
    expect(got).toBe("hi");
  });

  it("falls back when the clipboard refuses", async () => {
    let got = "";
    const refuses = { writeText: async () => { throw new Error("NotAllowedError"); } };
    expect(await copyText("hi", { clipboard: refuses, fallback: (t) => { got = t; return true; } })).toBe(true);
    expect(got).toBe("hi");
  });

  it("says so when nothing works", async () => {
    expect(await copyText("hi", { clipboard: undefined, fallback: () => false })).toBe(false);
  });
});
