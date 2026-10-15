// How the app uses the screen's width. Three sizes:
//   phone   (up to 767px):   one column, 520px at most, exactly as the app always was
//   tablet  (768-1023px):    the same single column, wider (720px); Threads still slides in
//   desktop (1024px and up): a rail of tabs on the left; Chat keeps Threads open beside it; Today and Settings in two columns
// The widths are Tailwind classes (md: is 768px, lg: is 1024px), so CSS does the switching. Only what has to be decided in
// code (Threads as a sidebar or a sheet) reads WIDE_QUERY, the same 1024px line.
import { useSyncExternalStore } from "react";
import type { Tab } from "./App";
import { has, type Caps } from "./capabilities";
import type { IconName } from "./components/Tile";

export const WIDE_QUERY = "(min-width: 1024px)";

/** The app column's width classes for a screen. The first class is always the phone width it has always had.
 *  Worked examples: "chat" -> 520px on a phone, 720px on a tablet, no limit on a desktop (Chat lays out its own Threads
 *  sidebar and reading column); "today" -> 520 / 720 / 1160 (two columns); "setup" -> 780 at every size. */
export function columnWidth(tab: Tab): string {
  if (tab === "setup") return "max-w-[780px]";
  const phoneAndTablet = "max-w-[520px] md:max-w-[720px]";
  if (tab === "chat") return `${phoneAndTablet} lg:max-w-none`;
  if (tab === "today") return `${phoneAndTablet} lg:max-w-[1160px]`;
  if (tab === "settings") return `${phoneAndTablet} lg:max-w-[1040px]`;
  return `${phoneAndTablet} lg:max-w-[820px]`;  // Brain, Money, the blocks gallery: one column as wide as Chat's
}

/** Whether the desktop rail shows beside a screen. Setup is a first-run flow on its own: "setup" -> no rail;
 *  every other screen ("today", "chat", "settings"...) -> the rail (on a desktop only; CSS hides it on smaller screens). */
export function showsRail(tab: Tab): boolean {
  return tab !== "setup";
}

export type RailItem = { tab: Tab; label: string; icon: IconName };

/** The desktop rail's tabs, for what this install has. Money needs the money ledger.
 *  Worked examples: caps {mail, money} -> Today, Chat, Money, Brain, Settings; caps {mail} -> Today, Chat, Brain, Settings;
 *  caps unknown (null) -> all five, as the app shows everything when the server doesn't say. */
export function railItems(caps: Caps): RailItem[] {
  const items: RailItem[] = [
    { tab: "today", label: "Today", icon: "sun" },
    { tab: "chat", label: "Chat", icon: "chat" },
    { tab: "money", label: "Money", icon: "rupee" },
    { tab: "brain", label: "Brain", icon: "brain" },
    { tab: "settings", label: "Settings", icon: "gear" },
  ];
  return items.filter((item) => item.tab !== "money" || has(caps, "money"));
}

/** Which rail tab lights up for a screen. The sample chat is reached from Settings, so "sample" -> "settings";
 *  "brain" -> "brain"; "today" -> "today". */
export function railTabFor(tab: Tab): Tab {
  return tab === "sample" ? "settings" : tab;
}

type MediaWindow = { matchMedia: (query: string) => MediaQueryList };

/** Whether the media query matches now; false where there is no window (tests, the server). */
export function mediaMatches(query: string, win: MediaWindow | undefined = globalThis.window): boolean {
  if (!win?.matchMedia) return false;
  return win.matchMedia(query).matches;
}

/** Calls onChange whenever the query starts or stops matching (the window is resized past it). Returns the unsubscribe. */
export function watchMedia(query: string, onChange: () => void, win: MediaWindow | undefined = globalThis.window): () => void {
  if (!win?.matchMedia) return () => {};
  const list = win.matchMedia(query);
  list.addEventListener("change", onChange);
  return () => list.removeEventListener("change", onChange);
}

/** True on a desktop-wide window (1024px and up), and it follows the window as it is resized. */
export function useWide(): boolean {
  return useSyncExternalStore(
    (onChange) => watchMedia(WIDE_QUERY, onChange),
    () => mediaMatches(WIDE_QUERY),
    () => false,
  );
}
