/** Where the user is: the server keeps a place name (never coordinates in what reaches the model), and the web app sends a
 * fix on open, after one ask. These are the pure decisions; LocationAsk and Settings' LocationRow render them. */
export type LocationInfo = { on: boolean | null; place: string; seen: string; home: string; home_set_by_user: boolean };
export type LocationRow = { sub: string; meta: string; state: "ok" | "off" | "none" };

export const ASK_TEXT = "Share where you are, for better answers? Odie uses the place name, not coordinates, in what it sends to your chat model.";
export const NOTE_TEXT = "Your model gets the place name; a point may reach OpenStreetMap if none nearby is known.";

/** Whether the one-line ask shows: only while nobody has answered it (`on` is null) and this browser can give a position.
 *  never asked, geolocation available -> true; never asked, a desktop without it -> false; "Not now" earlier -> false;
 *  allowed earlier -> false; nothing loaded yet -> false. */
export function shouldAsk(info: LocationInfo | null, supported: boolean): boolean {
  if (!info || !supported) return false;
  return info.on === null;
}

/** Whether to refresh the place silently on open: allowed earlier, and this browser can give a position.
 *  allowed, geolocation available -> true; never asked -> false; off -> false; allowed on a desktop without it -> false. */
export function shouldRefresh(info: LocationInfo | null, supported: boolean): boolean {
  if (!info || !supported) return false;
  return info.on === true;
}

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** The minutes east of UTC an ISO time was written in: "+05:30" -> 330; "Z" -> 0; none -> the browser's own. */
function offsetMinutes(iso: string): number {
  const m = /([+-])(\d\d):(\d\d)$/.exec(iso);
  if (m) return (m[1] === "-" ? -1 : 1) * (Number(m[2]) * 60 + Number(m[3]));
  if (iso.endsWith("Z")) return 0;
  return -new Date().getTimezoneOffset();
}

/** When a fix was seen, as the row says it, in the clock the fix was written in (the server's): the time alone on the
 *  same day as `now` ("14:12"), else the day too ("Sat 24 Oct 21:40"); "" for no time or one that can't be read. */
export function seenText(iso: string, now: Date): string {
  const at = new Date(iso);
  if (!iso || Number.isNaN(at.getTime())) return "";
  const shift = offsetMinutes(iso) * 60_000;
  const atThere = new Date(at.getTime() + shift);  // UTC fields of this date are the fix's own clock
  const nowThere = new Date(now.getTime() + shift);
  const hhmm = `${String(atThere.getUTCHours()).padStart(2, "0")}:${String(atThere.getUTCMinutes()).padStart(2, "0")}`;
  const sameDay = atThere.getUTCFullYear() === nowThere.getUTCFullYear() && atThere.getUTCMonth() === nowThere.getUTCMonth()
    && atThere.getUTCDate() === nowThere.getUTCDate();
  if (sameDay) return hhmm;
  return `${DAYS[atThere.getUTCDay()]} ${atThere.getUTCDate()} ${MONTHS[atThere.getUTCMonth()]} ${hhmm}`;
}

/** Settings' Location row, in words. The place has the sub line to itself (a long name truncates there and hides
 *  nothing else); seen and home go on the shorter meta line under it.
 *    on, a place known  -> sub "City of Northvale, Westshire", meta "seen 14:12 · home Northvale"
 *    on, nothing yet    -> sub "Waiting for the first fix", meta ""
 *    off                -> sub "Off"
 *    never asked        -> sub "Not asked yet" */
export function locationRow(info: LocationInfo, now: Date): LocationRow {
  if (info.on === null) return { sub: "Not asked yet", meta: "", state: "none" };
  if (info.on === false) return { sub: "Off", meta: "", state: "off" };
  if (!info.place) return { sub: "Waiting for the first fix", meta: "", state: "ok" };
  const details = [];
  const seen = seenText(info.seen, now);
  if (seen) details.push(`seen ${seen}`);
  if (info.home) details.push(`home ${info.home}`);
  return { sub: info.place, meta: details.join(" · "), state: "ok" };
}

/** Whether this browser can give a position at all (a desktop browser may not). */
export function geolocationSupported(): boolean {
  return typeof navigator !== "undefined" && !!navigator.geolocation;
}

/** One position from the browser, or null when it can't or won't give one; it asks the user the first time, by itself. */
export type Position = { lat: number; lon: number; at: string };

/** This browser's position with the moment it was taken in the device's own offset; "denied" when the user refused the
 * browser's own dialog (code 1); null when it can't answer (no support, a timeout, no fix). */
export function currentPosition(): Promise<Position | "denied" | null> {
  return new Promise((resolve) => {
    if (!geolocationSupported()) { resolve(null); return; }
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ lat: p.coords.latitude, lon: p.coords.longitude, at: localIso(new Date(p.timestamp)) }),
      (e) => resolve(e.code === 1 ? "denied" : null),
      { timeout: 8000, maximumAge: 600_000 },
    );
  });
}

/** What Allow leads to: a position is sent; a denial is kept as "Not now" (the browser would never ask again, so
 * neither should the line); nothing (a timeout, no support) leaves the line for next time. */
export function afterAllow(got: Position | "denied" | null): "send" | "decline" | "leave" {
  if (got === "denied") return "decline";
  if (got === null) return "leave";
  return "send";
}

/** A date as ISO text in the device's own offset: 2026-10-25T14:12:00+05:30. */
export function localIso(d: Date): string {
  const pad = (n: number) => String(Math.abs(n)).padStart(2, "0");
  const offset = -d.getTimezoneOffset();
  const sign = offset >= 0 ? "+" : "-";
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}${sign}${pad(Math.trunc(offset / 60))}:${pad(offset % 60)}`;
}
