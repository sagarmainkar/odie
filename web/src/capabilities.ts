import { useEffect, useState } from "react";
import { getJSON } from "./api";

/** What this install can do (mail, calendar, google, money, vault...), from /api/capabilities. null: not known yet, or
 *  the server didn't say; the app then shows everything, as it always did. */
export type Caps = ReadonlySet<string> | null;

let cached: Promise<Caps> | null = null;
let country = "";  // the computer's region (from the same answer): which market a new chat suggests

export function fetchCaps(refresh = false): Promise<Caps> {
  if (!cached || refresh) {
    cached = getJSON<{ caps: string[]; country?: string }>("/api/capabilities")
      .then((r) => { country = r.country ?? ""; return new Set(r.caps) as Caps; }).catch(() => null);
  }
  return cached;
}

export function userCountry(): string {
  return country;
}

export function has(caps: Caps, cap: string): boolean {
  return caps === null || caps.has(cap);
}

/** Items that name what they need, kept only when the install has it. */
export function shown<T extends { needs?: string }>(items: T[], caps: Caps): T[] {
  return items.filter((i) => !i.needs || has(caps, i.needs));
}

/** The Money tab without a money ledger is Today. */
export function tabFor<T extends string>(tab: T, caps: Caps): T | "today" {
  return tab === "money" && !has(caps, "money") ? "today" : tab;
}

export function useCaps(): Caps {
  const [caps, setCaps] = useState<Caps>(null);
  useEffect(() => {
    let live = true;
    fetchCaps().then((c) => { if (live) setCaps(c); });
    return () => { live = false; };
  }, []);
  // No live stream of its own: each EventSource holds one of the browser's six connections to this host, and what's
  // there (the add-ons' files) doesn't change while the app is open.
  return caps;
}
