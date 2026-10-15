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
