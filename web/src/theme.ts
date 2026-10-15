// The look: dark (night) when the phone is in dark mode or Dark is chosen; otherwise a wash that follows the time of
// day: warm in the morning, sky at noon, rose in the evening.
export type Tod = "dawn" | "noon" | "evening" | "night";
export type Look = "auto" | "light" | "dark";
const KEY = "odie.theme";
// The browser bar matches each wash's base colour.
const BASE: Record<Tod, string> = { dawn: "#F7F3EE", noon: "#F3F5F9", evening: "#F6F1F0", night: "#110F18" };

export function timeOfDay(hour: number): Tod {
  return hour >= 5 && hour < 11 ? "dawn" : hour >= 11 && hour < 16 ? "noon" : hour >= 16 && hour < 19 ? "evening" : "night";
}

/** Which wash to show.
 *    "dark", any time                    -> "night"
 *    "light" at 21:00                    -> "evening" (light never goes to night)
 *    "auto", the phone in dark mode      -> "night", at noon too
 *    "auto", the phone in light mode, 8:00 -> "dawn"; at 21:00 -> "evening" */
export function resolveLook(pref: Look, hour: number, systemDark = false): Tod {
  if (pref === "dark") return "night";
  if (pref === "auto" && systemDark) return "night";
  const t = timeOfDay(hour);
  if (t === "night") return hour >= 19 ? "evening" : "dawn";
  return t;
}

const DARK_QUERY = "(prefers-color-scheme: dark)";

/** Whether the phone (or computer) is in dark mode right now. */
export function systemDark(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia(DARK_QUERY).matches;
}

export function getLook(): Look {
  try {
    const v = localStorage.getItem(KEY);
    if (v === "light" || v === "dark") return v;
  } catch { /* private mode */ }
  return "auto";  // also covers the old "system" value
}

export function applyLook(pref: Look, hour = new Date().getHours(), dark = systemDark()): Tod {
  const tod = resolveLook(pref, hour, dark);
  document.documentElement.dataset.tod = tod;
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", BASE[tod]);
  try { if (pref === "auto") localStorage.removeItem(KEY); else localStorage.setItem(KEY, pref); } catch { /* ignore */ }
  return tod;
}

export function initLook() { applyLook(getLook()); }

/** Re-applies the look every few minutes so the wash follows the clock while the app stays open, and at once when the
 *  phone switches between light and dark mode. */
export function startLookClock(everyMs = 5 * 60_000, apply: () => void = () => applyLook(getLook())): () => void {
  const id = setInterval(apply, everyMs);
  const scheme = typeof window !== "undefined" && window.matchMedia ? window.matchMedia(DARK_QUERY) : null;
  scheme?.addEventListener?.("change", apply);
  // Timers sleep while the phone is locked: re-apply the moment Odie is back on screen, so dawn doesn't show at night.
  const onVisible = () => { if (document.visibilityState === "visible") apply(); };
  const doc = typeof document !== "undefined" ? document : null;
  doc?.addEventListener("visibilitychange", onVisible);
  return () => { clearInterval(id); doc?.removeEventListener("visibilitychange", onVisible); scheme?.removeEventListener?.("change", apply); };
}
