// The Threads sidebar on a wide screen (1024px and up, layout.ts): open beside the chat, or hidden to give the chat
// the room. Hiding it is a choice for this device only, kept in this browser like the look (theme.ts): a laptop and an
// iPad can each keep their own. Below 1024px Threads is a sheet (ThreadsSheet) and none of this applies.
import { useEffect, useState } from "react";

export const SIDEBAR_KEY = "odie.threadsSidebar";
/** The only value ever stored: the sidebar is hidden. Open is the default, so open removes the key. */
export const HIDDEN = "hidden";

type Storage = { getItem: (k: string) => string | null; setItem: (k: string, v: string) => void; removeItem: (k: string) => void };

function deviceStorage(): Storage | undefined {
  try {
    if (typeof localStorage === "undefined") return undefined;
    return localStorage;
  } catch {
    return undefined;  // a browser that blocks storage can throw on the name alone
  }
}

/** Whether a stored value means the sidebar is open. Only "hidden" hides it:
 *  null (never chosen) -> open; "hidden" -> hidden; "something else" -> open, as it always was. */
export function openFromStored(value: string | null): boolean {
  return value !== HIDDEN;
}

/** This device's choice: open unless it stored "hidden". Storage that can't be read (private mode) -> open. */
export function readSidebarOpen(storage: Storage | undefined = deviceStorage()): boolean {
  if (!storage) return true;
  try {
    return openFromStored(storage.getItem(SIDEBAR_KEY));
  } catch {
    return true;
  }
}

/** Keeps the choice on this device: hidden -> "hidden" stored; open -> the key removed. A browser that won't keep
 *  it just forgets it on a reload. */
export function saveSidebarOpen(open: boolean, storage: Storage | undefined = deviceStorage()): void {
  if (!storage) return;
  try {
    if (open) storage.removeItem(SIDEBAR_KEY);
    else storage.setItem(SIDEBAR_KEY, HIDDEN);
  } catch { /* not kept: it lasts until a reload */ }
}

/** The other state: open -> hidden; hidden -> open. */
export function toggled(open: boolean): boolean {
  return !open;
}

/** Whether a platform name is Apple's, where the shortcut uses Cmd. An iPad says "MacIntel" (or "iPad") ->
 *  Apple; "iPhone" -> Apple; "Win32" -> no; "Linux x86_64" -> no. */
export function isApple(platform: string): boolean {
  return /Mac|iPhone|iPad|iPod/.test(platform);
}

type KeyPress = { key: string; metaKey: boolean; ctrlKey: boolean; altKey: boolean; shiftKey: boolean; repeat?: boolean; isComposing?: boolean };

/** Whether a key press is the sidebar's shortcut: Cmd+\ on a Mac or an iPad, Ctrl+\ elsewhere, nothing else held.
 *  A modifier is always needed, so typing a backslash in the composer types it.
 *    "\" with Cmd on a Mac -> toggles;  "\" with Ctrl on Windows -> toggles;  "\" alone -> typed, not taken;
 *    "\" with Cmd+Shift -> no;  "\" with Ctrl on a Mac -> no;  a held-down Cmd+\ repeating -> only the first press;
 *    a press while an input method is still composing a character -> no. */
export function isToggleShortcut(press: KeyPress, apple: boolean): boolean {
  if (press.key !== "\\") return false;
  if (press.repeat || press.isComposing) return false;
  if (press.altKey || press.shiftKey) return false;
  if (apple) return press.metaKey && !press.ctrlKey;
  return press.ctrlKey && !press.metaKey;
}

/** The shortcut as each keyboard writes it, for the buttons' tooltips: Apple -> "⌘\"; others -> "Ctrl+\". */
export function shortcutText(apple: boolean): string {
  return apple ? "⌘\\" : "Ctrl+\\";
}

/** Whether the chat header shows the Threads pill. Below 1024px Threads is a sheet the pill opens, so always:
 *  (not wide, either) -> shows. On a wide screen it brings a hidden sidebar back: (wide, open) -> no pill;
 *  (wide, hidden) -> the pill. */
export function showsThreadsPill(wide: boolean, sidebarOpen: boolean): boolean {
  if (!wide) return true;
  return !sidebarOpen;
}

function platformName(): string {
  if (typeof navigator === "undefined") return "";
  return navigator.platform || "";
}

/** True on a Mac, an iPad or an iPhone (the shortcut there is Cmd+\). */
export function onApple(): boolean {
  return isApple(platformName());
}

/** The sidebar's open state for this device, read once on mount and kept as it changes. While `shortcutOn` (a wide
 *  screen with the chat showing) Cmd+\ / Ctrl+\ toggles it from anywhere on the page. */
export function useThreadsSidebar(shortcutOn: boolean): { open: boolean; setOpen: (open: boolean) => void } {
  const [open, setOpen] = useState(() => readSidebarOpen());
  useEffect(() => { saveSidebarOpen(open); }, [open]);
  useEffect(() => {
    if (!shortcutOn) return;
    const apple = onApple();
    function onKey(e: KeyboardEvent) {
      if (!isToggleShortcut(e, apple)) return;
      e.preventDefault();
      setOpen(toggled);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [shortcutOn]);
  return { open, setOpen };
}
