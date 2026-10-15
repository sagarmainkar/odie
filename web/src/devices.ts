/** Paired devices: while pairing is on, the server answers only browsers it knows. A browser that isn't paired sees
 * the Private screen, and pairs there with a code (from a paired device's Settings, or its QR code) or the passcode. */
import { userLocale } from "./locale";

export const PRIVATE_EVENT = "odie-private";

export type Device = { id: number; name: string; created_at: number; last_seen_at: number; this: boolean };
export type PairStatus = { on: boolean; paired: boolean; devices: number; passcode: boolean };
export type NewCode = { code: string; url: string; svg: string; expires_in: number };

/** The code a pairing link carries ("#pair=ABCD-EFGH": a fragment, so it never reaches a server log), or null. */
export function codeFromHash(hash: string): string | null {
  const m = /^#pair=([A-Za-z0-9]{4})-?([A-Za-z0-9]{4})$/.exec(hash);
  return m ? `${m[1]}-${m[2]}`.toUpperCase() : null;
}

/** What the code box shows as it's typed: capitals, a dash after four. */
export function typedCode(text: string): string {
  const raw = text.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 8);
  return raw.length > 4 ? `${raw.slice(0, 4)}-${raw.slice(4)}` : raw;
}

export function lastSeen(seconds: number, nowMs: number = Date.now()): string {
  const s = Math.max(0, nowMs / 1000 - seconds);
  if (s < 120) return "Active now";
  if (s < 3600) return `${Math.floor(s / 60)} minutes ago`;
  if (s < 7200) return "An hour ago";
  if (s < 86400) return `${Math.floor(s / 3600)} hours ago`;
  if (s < 2 * 86400) return "Yesterday";
  if (s < 7 * 86400) return `${Math.floor(s / 86400)} days ago`;
  return new Date(seconds * 1000).toLocaleDateString(userLocale(), { day: "numeric", month: "short", year: "numeric" });
}

export function needsPairing(s: PairStatus | null): boolean {
  return !!s && s.on && !s.paired;
}

/** Without a recovery passcode, losing the only paired device (or its cookie) leaves no way back in. */
export function needsPasscode(s: PairStatus | null): boolean {
  return !!s && s.on && !s.passcode;
}

/** A link to this computer itself (localhost): another device can't open it. */
export function loopback(url: string): boolean {
  const host = new URL(url).hostname;
  return host === "localhost" || host === "[::1]" || host === "::1" || /^127\./.test(host);
}

/** A fetch that calls onPrivate when an API says this Odie is private (this browser was removed, say). */
export function watchPrivate(f: typeof fetch, onPrivate: () => void): typeof fetch {
  return async (...args: Parameters<typeof fetch>) => {
    const r = await f(...args);
    if (r.status === 401) {
      const b = await r.clone().json().catch(() => null);
      if (b && b.pair === true) onPrivate();
    }
    return r;
  };
}
