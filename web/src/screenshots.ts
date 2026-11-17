/** The browser's screenshots in a reply: live while it works (the latest page, large), then a strip. */
import type { Media } from "./media";

export function site(url: string): string {
  try {
    const host = new URL(url).hostname;
    return host.startsWith("www.") ? host.slice(4) : host;
  } catch {
    return url;
  }
}

/** The screenshots together (in the order they were taken), and everything else apart. */
export function groupMedia(items: Media[]): { shots: Media[]; rest: Media[] } {
  return { shots: items.filter((m) => m.kind === "screenshot"), rest: items.filter((m) => m.kind !== "screenshot") };
}

/** While the reply is being written: the page the browser is on now. */
export function liveShot(items: Media[], streaming: boolean): Media | null {
  if (!streaming) return null;
  const shots = items.filter((m) => m.kind === "screenshot");
  return shots.length ? shots[shots.length - 1] : null;
}

/** Which browser tab a reply's Watch (and "Open the page live") opens, or undefined for no button at all.
 * `canOpenLive`: signed-in browsing is on; the live view exists only then. The tab saved with the reply's latest
 * screenshot wins (it is where that page is); a screenshot from before tabs were saved falls back to the chat's tab.
 *   on, latest screenshot saved in "chat-2026-11-17"            -> "chat-2026-11-17"
 *   on, an older screenshot with no tab, the chat is "chat-2026-11-02" -> "chat-2026-11-02"
 *   on, no tab on the screenshot and none from the chat          -> undefined
 *   on, no screenshots in the reply                              -> undefined
 *   off, whatever else                                           -> undefined */
export function watchTab(shots: Media[], chatTab: string | undefined, canOpenLive: boolean): string | undefined {
  if (!canOpenLive || shots.length === 0) return undefined;
  const latest = shots[shots.length - 1];
  return latest.tab ?? chatTab;
}
