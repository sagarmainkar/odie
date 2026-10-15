/** The language and region the app formats dates, times and numbers in: the one the computer running the assistant
 * is set to (from /api/profile), remembered on this device so the first screen already uses it. Else the browser's. */
const KEY = "odie.locale";

function stored(): string | null {
  try { return typeof localStorage === "undefined" ? null : localStorage.getItem(KEY); } catch { return null; }
}

let current: string = stored() ?? (typeof navigator !== "undefined" && navigator.language ? navigator.language : "en-US");

export function userLocale(): string { return current; }

export function rememberLocale(locale: string): void {
  if (!locale || locale === current) return;
  current = locale;
  try { localStorage.setItem(KEY, locale); } catch { /* private mode: still used for this visit */ }
}

/** Lakh and crore (1.2L, 3.4Cr) are how amounts are read in India; elsewhere plain thousands. */
export function usesLakhCrore(): boolean { return /-IN$/.test(current); }
