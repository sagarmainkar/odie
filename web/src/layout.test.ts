import { describe, expect, it } from "vitest";
import { columnWidth, mediaMatches, railItems, railTabFor, showsRail, watchMedia, WIDE_QUERY } from "./layout";

describe("columnWidth", () => {
  it("keeps every screen's phone width as it always was", () => {
    for (const tab of ["chat", "today", "settings", "brain", "sample", "money"] as const) {
      expect(columnWidth(tab).split(" ")[0]).toBe("max-w-[520px]");
    }
    expect(columnWidth("setup")).toBe("max-w-[780px]");
  });
  it("widens to 720px on a tablet, and per screen on a desktop", () => {
    expect(columnWidth("chat")).toContain("md:max-w-[720px]");
    expect(columnWidth("chat")).toContain("lg:max-w-none");
    expect(columnWidth("today")).toContain("lg:max-w-[1160px]");
    expect(columnWidth("settings")).toContain("lg:max-w-[1040px]");
    expect(columnWidth("brain")).toContain("lg:max-w-[820px]");
  });
});

describe("the desktop rail", () => {
  it("shows beside every screen but Setup", () => {
    expect(showsRail("today")).toBe(true);
    expect(showsRail("chat")).toBe(true);
    expect(showsRail("setup")).toBe(false);
  });
  it("has Money only with the money ledger", () => {
    expect(railItems(new Set(["mail", "money"])).map((i) => i.tab)).toEqual(["today", "chat", "money", "brain", "settings"]);
    expect(railItems(new Set(["mail"])).map((i) => i.tab)).toEqual(["today", "chat", "brain", "settings"]);
    expect(railItems(null).map((i) => i.tab)).toEqual(["today", "chat", "money", "brain", "settings"]);
  });
  it("lights Settings for the blocks gallery, which opens from Settings", () => {
    expect(railTabFor("sample")).toBe("settings");
    expect(railTabFor("brain")).toBe("brain");
  });
});

/** A stand-in window whose width can change, with matchMedia for "(min-width: Npx)" queries. */
function fakeWindow(width: number) {
  const listeners = new Set<() => void>();
  const win = {
    width,
    matchMedia(query: string) {
      const min = Number(query.match(/min-width:\s*(\d+)px/)?.[1] ?? 0);
      return {
        get matches() { return win.width >= min; },
        addEventListener: (_: string, f: () => void) => listeners.add(f),
        removeEventListener: (_: string, f: () => void) => listeners.delete(f),
      } as unknown as MediaQueryList;
    },
    resize(to: number) { win.width = to; listeners.forEach((f) => f()); },
    listeners,
  };
  return win;
}

describe("mediaMatches and watchMedia (useWide: Threads as a sidebar or a sheet)", () => {
  it("is wide from 1024px", () => {
    expect(mediaMatches(WIDE_QUERY, fakeWindow(390))).toBe(false);
    expect(mediaMatches(WIDE_QUERY, fakeWindow(1023))).toBe(false);
    expect(mediaMatches(WIDE_QUERY, fakeWindow(1024))).toBe(true);
  });
  it("is never wide without a window (tests, the server)", () => {
    expect(mediaMatches(WIDE_QUERY, undefined)).toBe(false);
  });
  it("tells when the window is resized past the line, and stops when unsubscribed", () => {
    const win = fakeWindow(800);
    let changes = 0;
    const stop = watchMedia(WIDE_QUERY, () => { changes += 1; }, win);
    win.resize(1280);
    expect(changes).toBe(1);
    expect(mediaMatches(WIDE_QUERY, win)).toBe(true);
    stop();
    expect(win.listeners.size).toBe(0);
  });
});
