import { describe, expect, it } from "vitest";
import {
  HIDDEN, SIDEBAR_KEY, isApple, isToggleShortcut, openFromStored, readSidebarOpen, saveSidebarOpen, shortcutText,
  showsThreadsPill, toggled,
} from "./threadsSidebar";

/** A stand-in for localStorage: a plain map, or one that throws like a browser that won't keep anything. */
function memoryStorage(start: Record<string, string> = {}) {
  const items = new Map(Object.entries(start));
  return {
    getItem: (k: string) => items.get(k) ?? null,
    setItem: (k: string, v: string) => { items.set(k, v); },
    removeItem: (k: string) => { items.delete(k); },
    items,
  };
}
const brokenStorage = {
  getItem: () => { throw new Error("blocked"); },
  setItem: () => { throw new Error("blocked"); },
  removeItem: () => { throw new Error("blocked"); },
};

const key = (k: string, mods: { meta?: boolean; ctrl?: boolean; alt?: boolean; shift?: boolean; repeat?: boolean; isComposing?: boolean } = {}) => ({
  key: k, metaKey: !!mods.meta, ctrlKey: !!mods.ctrl, altKey: !!mods.alt, shiftKey: !!mods.shift,
  repeat: !!mods.repeat, isComposing: !!mods.isComposing,
});

describe("what the stored value means", () => {
  it("is open unless the device has stored that it is hidden", () => {
    expect(openFromStored(null)).toBe(true);  // never chosen: the default is open
    expect(openFromStored(HIDDEN)).toBe(false);
    expect(openFromStored("something else")).toBe(true);  // a value we don't know: open, as it always was
  });
  it("reads the device's choice, open when nothing is stored or storage can't be read", () => {
    expect(readSidebarOpen(memoryStorage())).toBe(true);
    expect(readSidebarOpen(memoryStorage({ [SIDEBAR_KEY]: HIDDEN }))).toBe(false);
    expect(readSidebarOpen(brokenStorage)).toBe(true);
    expect(readSidebarOpen(undefined)).toBe(true);  // no storage at all (the server, a test)
  });
});

describe("the toggle", () => {
  it("flips open and hidden", () => {
    expect(toggled(true)).toBe(false);
    expect(toggled(false)).toBe(true);
  });
  it("keeps only 'hidden'; open takes the key away, so the default stays the default", () => {
    const storage = memoryStorage();
    saveSidebarOpen(false, storage);
    expect(storage.items.get(SIDEBAR_KEY)).toBe(HIDDEN);
    expect(readSidebarOpen(storage)).toBe(false);
    saveSidebarOpen(true, storage);
    expect(storage.items.has(SIDEBAR_KEY)).toBe(false);
    expect(readSidebarOpen(storage)).toBe(true);
  });
  it("doesn't fail where storage throws (it then lasts until a reload)", () => {
    expect(() => saveSidebarOpen(false, brokenStorage)).not.toThrow();
  });
});

describe("the keyboard shortcut", () => {
  it("is Cmd+\\ on a Mac or an iPad", () => {
    expect(isToggleShortcut(key("\\", { meta: true }), true)).toBe(true);
    expect(isToggleShortcut(key("\\", { ctrl: true }), true)).toBe(false);
  });
  it("is Ctrl+\\ elsewhere", () => {
    expect(isToggleShortcut(key("\\", { ctrl: true }), false)).toBe(true);
    expect(isToggleShortcut(key("\\", { meta: true }), false)).toBe(false);
  });
  it("never takes a backslash being typed, or another key", () => {
    expect(isToggleShortcut(key("\\"), true)).toBe(false);
    expect(isToggleShortcut(key("\\"), false)).toBe(false);
    expect(isToggleShortcut(key("\\", { shift: true }), true)).toBe(false);  // "|"
    expect(isToggleShortcut(key("\\", { meta: true, alt: true }), true)).toBe(false);
    expect(isToggleShortcut(key("\\", { meta: true, ctrl: true }), true)).toBe(false);
    expect(isToggleShortcut(key("b", { meta: true }), true)).toBe(false);
  });
  it("ignores a held-down key and a keyboard still composing a character", () => {
    expect(isToggleShortcut(key("\\", { meta: true, repeat: true }), true)).toBe(false);
    expect(isToggleShortcut(key("\\", { meta: true, isComposing: true }), true)).toBe(false);
  });
  it("knows Apple devices by their platform (an iPad reports itself as a Mac)", () => {
    expect(isApple("MacIntel")).toBe(true);
    expect(isApple("iPad")).toBe(true);
    expect(isApple("iPhone")).toBe(true);
    expect(isApple("Win32")).toBe(false);
    expect(isApple("Linux x86_64")).toBe(false);
    expect(isApple("")).toBe(false);
  });
  it("is written the way each keyboard says it", () => {
    expect(shortcutText(true)).toBe("⌘\\");
    expect(shortcutText(false)).toBe("Ctrl+\\");
  });
});

describe("when the header's Threads pill shows", () => {
  it("always below 1024px, where Threads is a sheet", () => {
    expect(showsThreadsPill(false, true)).toBe(true);
    expect(showsThreadsPill(false, false)).toBe(true);
  });
  it("on a wide screen only while the sidebar is hidden", () => {
    expect(showsThreadsPill(true, true)).toBe(false);
    expect(showsThreadsPill(true, false)).toBe(true);
  });
});
