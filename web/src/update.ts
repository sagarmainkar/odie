// Updating Odie from the app: whether a newer version is on origin, and when the update it started has landed.
// The server (/api/update) does the fetch and the compare and starts `odie update`; this is the app's small shared
// state around it, so Settings (the row and button), the rail (a dot) and the curtain all see the same answer.
import { useEffect, useSyncExternalStore } from "react";
import { getJSON, postJSON } from "./api";

export type UpdateInfo = { current: string; latest: string; behind: boolean; checked_at: number; running: boolean };
export type UpdateState = { info: UpdateInfo | null; checking: boolean; error: string | null; checkedAt: number | null };

export const CHECK_EVERY_MS = 60 * 60 * 1000;  // an hour: a check is a git fetch on the Mac, nothing the phone feels
const POLL_EVERY_MS = 60 * 1000;  // how often the app looks at the clock to see whether an hour has passed

/**
 * Whether it's time to ask the server again: never asked, or an hour or more since the last time.
 *   never → true;  checked 20 min ago → false;  checked 61 min ago → true
 */
export function isStale(checkedAt: number | null, now: number): boolean {
  if (checkedAt === null) return true;
  return now - checkedAt >= CHECK_EVERY_MS;
}

/**
 * Whether the update has landed: the server answers again with a different version than the one it ran before.
 *   before "191cd0c", health {version: "191cd0c"} → false (still the old server, or its last breath);
 *   before "191cd0c", health {version: "a3f9e01"} → true;  health null (server restarting) → false
 */
export function updateLanded(before: string, health: { version?: string } | null): boolean {
  if (!health || !health.version) return false;
  return health.version !== before;
}

/** "Checked just now", "Checked 5 min ago", "Checked 2 h ago": for the Settings row. */
export function checkedAgo(checkedAt: number | null, now: number): string {
  if (checkedAt === null) return "Not checked yet";
  const minutes = Math.floor((now - checkedAt) / 60000);
  if (minutes < 1) return "Checked just now";
  if (minutes < 60) return `Checked ${minutes} min ago`;
  return `Checked ${Math.floor(minutes / 60)} h ago`;
}

// ── the shared state ──
let state: UpdateState = { info: null, checking: false, error: null, checkedAt: null };
const listeners = new Set<() => void>();
function set(next: Partial<UpdateState>) {
  state = { ...state, ...next };
  listeners.forEach((l) => l());
}

/** Asks the server. `force` is "Check now": the server fetches even if it answered minutes ago. */
export async function checkForUpdate(force = false): Promise<void> {
  if (state.checking) return;
  set({ checking: true, error: null });
  try {
    const info = await getJSON<UpdateInfo>(`/api/update${force ? "?force=1" : ""}`);
    set({ info, checking: false, checkedAt: Date.now() });
  } catch (e) {
    set({ checking: false, error: e instanceof Error ? e.message : "Couldn't check", checkedAt: Date.now() });
  }
}

export function startUpdate(): Promise<{ started: boolean; from: string }> {
  return postJSON<{ started: boolean; from: string }>("/api/update", {});
}

/** The shared state, plus the hourly check and the one on coming back to the app, when `enabled` (the update cap). */
export function useUpdate(enabled: boolean): UpdateState {
  const s = useSyncExternalStore((l) => { listeners.add(l); return () => { listeners.delete(l); }; }, () => state);
  useEffect(() => {
    if (!enabled) return;
    const whenStale = () => { if (isStale(state.checkedAt, Date.now())) void checkForUpdate(); };
    whenStale();
    const timer = setInterval(whenStale, POLL_EVERY_MS);
    const onVisible = () => { if (document.visibilityState === "visible") whenStale(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => { clearInterval(timer); document.removeEventListener("visibilitychange", onVisible); };
  }, [enabled]);
  return s;
}

/** After an update: forget the old app shell (service workers and their caches), then load the new one. */
export async function reloadFresh(): Promise<void> {
  try {
    if ("serviceWorker" in navigator) {
      const regs = await navigator.serviceWorker.getRegistrations();
      await Promise.all(regs.map((r) => r.unregister()));
    }
    if ("caches" in window) {
      const names = await caches.keys();
      await Promise.all(names.map((n) => caches.delete(n)));
    }
  } catch { /* a browser without them: the reload alone is fine */ }
  location.reload();
}
