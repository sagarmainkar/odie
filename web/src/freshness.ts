// Picking up a new version of the app by itself. The service worker (sw.ts) takes over as soon as a new one
// installs; this asks it to look for one at the moments that matter, and reloads the page onto the new version
// only when that loses nothing. Otherwise a quiet "New version · Reload" pill waits, and the page reloads at the next
// safe moment (the answer ends, the app is put away).
import { useEffect, useSyncExternalStore } from "react";
import { getJSON } from "./api";

declare const __ODIE_BUILD__: string;

/** The commit this page was built from (vite.config.ts writes it in); "dev" from the dev server. */
export const BUILD: string = typeof __ODIE_BUILD__ === "string" ? __ODIE_BUILD__ : "dev";

export const CHECK_EVERY_MS = 15 * 60 * 1000;

/** What keeps a reload waiting: an answer streaming in, a voice turn, an approval waiting for a tap, text typed in
 *  the ask box. "stream" and "approval" live on the server too, so a hidden app may reload over them. */
export type Hold = "stream" | "voice" | "approval" | "draft" | string;
const SERVER_KEEPS = new Set(["stream", "approval"]);

/**
 * Whether the server serves a different build than this page runs, so a newer version is worth fetching.
 *   mine "a1b2c3d", served "e4f5a6b" -> true;  the same -> false;
 *   mine "dev" (the dev server) -> false;  served missing or "" (an older server, or a browser not paired) -> false
 */
export function buildDiffers(mine: string, served: string | undefined): boolean {
  if (mine === "dev") return false;
  if (!served) return false;
  return served !== mine;
}

export type Freshness = {
  hold: (why: Hold, on: boolean) => void;
  arrived: () => void;
  hidden: () => void;
  tap: () => void;
  pill: () => boolean;
  showPill: () => void;
  subscribe: (fn: () => void) => () => void;
};

/** The reload's small state: what holds it, and whether a new version is waiting. */
export function createFreshness({ reload }: { reload: () => void }): Freshness {
  const holds = new Set<string>();
  const listeners = new Set<() => void>();
  let waiting = false;  // a new version took control of the page; it runs the old one until it reloads
  let pillShown = false;
  let reloaded = false;

  const notify = () => { for (const fn of listeners) fn(); };
  const reloadOnce = () => {
    if (reloaded) return;
    reloaded = true;
    reload();
  };

  /**
   * Whether reloading now loses nothing. Visible, every hold counts; hidden, only the ones the server doesn't keep.
   *   no holds -> true;  {"stream"} visible -> false;  {"stream", "approval"} hidden -> true;
   *   {"draft"} hidden -> false (the typed text is only on this page);  {"voice"} hidden -> false
   */
  const safe = (isHidden: boolean): boolean => {
    for (const why of holds) {
      if (isHidden && SERVER_KEEPS.has(why)) continue;
      return false;
    }
    return true;
  };

  const reloadIfSafe = (isHidden: boolean) => {
    if (!waiting) return;
    if (safe(isHidden)) reloadOnce();
  };

  return {
    hold(why, on) {
      if (on) holds.add(why);
      else holds.delete(why);
      if (!on) reloadIfSafe(false);
    },
    arrived() {
      waiting = true;
      if (safe(false)) { reloadOnce(); return; }
      pillShown = true;
      notify();
    },
    hidden() { reloadIfSafe(true); },
    tap() { reloadOnce(); },
    pill() { return pillShown; },
    showPill() {
      if (pillShown) return;
      pillShown = true;
      notify();
    },
    subscribe(fn) {
      listeners.add(fn);
      return () => { listeners.delete(fn); };
    },
  };
}

/** The page's one copy. */
export const fresh = createFreshness({ reload: () => location.reload() });

/**
 * Asks for a new version when the app comes back into view, on focus, when the network returns, and every
 * 15 minutes while it is visible; each time it also reads the server's build. A different build asks the service
 * worker once more, or (no service worker: `update` is null) shows the pill, since only a reload brings it.
 * Going out of view is a safe moment to reload. Returns the function that stops it all.
 */
export function startUpdateChecks({ update, health, mine, fresh: state, everyMs = CHECK_EVERY_MS }: {
  update: (() => Promise<void>) | null; health: () => Promise<{ build?: string } | null>; mine: string;
  fresh: Freshness; everyMs?: number;
}): () => void {
  const ask = () => {
    if (update) void update().catch(() => {});
  };
  const readBuild = async () => {
    let answer: { build?: string } | null = null;
    try { answer = await health(); } catch { return; }
    if (!buildDiffers(mine, answer?.build)) return;
    if (update) ask();
    else state.showPill();
  };
  const check = () => {
    ask();
    void readBuild();
  };
  const onVisibility = () => {
    if (document.visibilityState === "visible") check();
    else state.hidden();
  };
  const onTimer = () => {
    if (document.visibilityState === "visible") check();
  };
  document.addEventListener("visibilitychange", onVisibility);
  window.addEventListener("focus", check);
  window.addEventListener("online", check);
  const timer = window.setInterval(onTimer, everyMs);
  return () => {
    document.removeEventListener("visibilitychange", onVisibility);
    window.removeEventListener("focus", check);
    window.removeEventListener("online", check);
    window.clearInterval(timer);
  };
}

/** Starts it all for this page: the service worker's registration (when there is one), the switch to a new worker,
 *  and the checks. A page that had no worker yet sees its first one take control; that is not a new version. */
export function startFreshness(): () => void {
  const sw = "serviceWorker" in navigator ? navigator.serviceWorker : null;
  let update: (() => Promise<void>) | null = null;
  let onControl: (() => void) | null = null;
  if (sw) {
    update = async () => {
      const reg = await sw.getRegistration();
      if (reg) await reg.update();
    };
    let hadWorker = !!sw.controller;
    onControl = () => {
      if (!hadWorker) { hadWorker = true; return; }
      fresh.arrived();
    };
    sw.addEventListener("controllerchange", onControl);
  }
  const stop = startUpdateChecks({ update, health: () => getJSON<{ build?: string }>("/api/health"), mine: BUILD, fresh });
  return () => {
    stop();
    if (sw && onControl) sw.removeEventListener("controllerchange", onControl);
  };
}

/** Keeps the reload waiting while `on` is true: useHoldReload("stream", busy). */
export function useHoldReload(why: Hold, on: boolean): void {
  useEffect(() => {
    fresh.hold(why, on);
    return () => fresh.hold(why, false);
  }, [why, on]);
}

/** Whether the "New version · Reload" pill shows. */
export function useNewVersionPill(): boolean {
  return useSyncExternalStore(fresh.subscribe, fresh.pill, fresh.pill);
}
