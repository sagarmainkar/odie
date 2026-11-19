import { useSyncExternalStore } from "react";

// The look: dark (night) when the phone is in dark mode or Dark is chosen; otherwise a wash that follows the time of
// day: warm in the morning, sky at noon, rose in the evening.
export type Tod = "dawn" | "noon" | "evening" | "night";
export type Look = "auto" | "light" | "dark";
const KEY = "odie.theme";
// The browser bar matches each wash's base colour.
const BASE: Record<Tod, string> = { dawn: "#F7F3EE", noon: "#F3F5F9", evening: "#F6F1F0", night: "#110F18" };

// The style, under the look: Glass (the washes and frosted cards, the default) or Newspaper (ink on paper, set in
// serifs). Auto, Light and Dark still choose day or night in either; Newspaper's night is its dark edition. The choice
// is kept in this browser like the look, and shows as data-style="paper" on <html> (no attribute for Glass).
export type Style = "glass" | "paper";
const STYLE_KEY = "odie.style";
const STYLE_CHANGED = "odie:style";
// The browser bar in Newspaper: the paper's own colour by day, the dark edition's charcoal at night.
const PAPER_DAY = "#F3F2EE";
const PAPER_NIGHT = "#1E1D1B";

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

/** The browser bar's colour: the wash's base in Glass; the paper, or the dark edition's charcoal, in Newspaper.
 *    ("dawn", "glass")  -> "#F7F3EE" (the morning wash)
 *    ("noon", "paper")  -> "#F3F2EE" (paper, whatever the hour)
 *    ("night", "paper") -> "#1E1D1B" (the dark edition) */
export function barColour(tod: Tod, style: Style): string {
  if (style === "glass") return BASE[tod];
  if (tod === "night") return PAPER_NIGHT;
  return PAPER_DAY;
}

export function applyLook(pref: Look, hour = new Date().getHours(), dark = systemDark()): Tod {
  const tod = resolveLook(pref, hour, dark);
  document.documentElement.dataset.tod = tod;
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", barColour(tod, shownStyle()));
  try { if (pref === "auto") localStorage.removeItem(KEY); else localStorage.setItem(KEY, pref); } catch { /* ignore */ }
  return tod;
}

/** The style kept in this browser; Glass when none was chosen or storage can't be read. */
export function getStyle(): Style {
  try {
    if (localStorage.getItem(STYLE_KEY) === "paper") return "paper";
  } catch { /* private mode */ }
  return "glass";
}

/** The style on screen now, read from <html>; Glass where there is no page (tests, the server render). */
export function shownStyle(): Style {
  if (typeof document === "undefined") return "glass";
  if (document.documentElement?.dataset?.style === "paper") return "paper";
  return "glass";
}

// Puts the style on <html>: data-style="paper" for Newspaper, no attribute at all for Glass.
function showStyle(style: Style) {
  const root = document.documentElement;
  if (style === "paper") root.dataset.style = "paper";
  else delete root.dataset.style;
}

/** Switches the style (Settings → Look), keeps it, recolours the browser bar, and tells the screens that draw
 *  something of their own for it (Pulse's masthead). Glass removes the key, as Auto does for the look. */
export function applyStyle(style: Style) {
  showStyle(style);
  try { if (style === "paper") localStorage.setItem(STYLE_KEY, style); else localStorage.removeItem(STYLE_KEY); } catch { /* ignore */ }
  applyLook(getLook());
  window.dispatchEvent(new Event(STYLE_CHANGED));
}

function onStyleChange(changed: () => void): () => void {
  window.addEventListener(STYLE_CHANGED, changed);
  return () => window.removeEventListener(STYLE_CHANGED, changed);
}

/** The style on screen, redrawn when Settings changes it. */
export function useStyle(): Style {
  return useSyncExternalStore(onStyleChange, shownStyle, shownStyle);
}

/** The line under Settings → Look (Settings.tsx), for the style picked: Glass explains its washes; Newspaper its two editions.
 *  "glass" -> "Auto follows your phone: … rose in the evening."; "paper" -> "Ink on paper, set in serifs. Auto …" */
export function lookNote(style: Style): string {
  if (style === "paper") return "Ink on paper, set in serifs. Auto follows your phone: the dark edition in dark mode, paper in light mode.";
  return "Auto follows your phone: dark in dark mode; in light mode the colour follows the time of day, warm in the morning, sky at noon, rose in the evening.";
}

export function initLook() {
  showStyle(getStyle());
  applyLook(getLook());
}

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
