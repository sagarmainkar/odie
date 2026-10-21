/** Settings → Mac apps: whether Odie may read each of the Mac's own apps (Mail, Calendar, Reminders), as
 * macOS grants it. The dialog that grants it appears only on the Mac itself, so a phone can only look. */
export type MacAppStatus = "granted" | "denied" | "unknown";
export type MacAppRow = { id: "mail" | "calendar" | "reminders" | "contacts" | string; name: string; status: MacAppStatus };
export type MacApps = { mac: boolean; apps: MacAppRow[]; default_calendar: string };
export type MacCalendar = { name: string; writable: boolean };

/** Whether this page is open on a Mac, where the permission dialog can appear (an iPad says Macintosh too, but has
 * touch points). Safari on a MacBook -> true; the iPhone app -> false. */
export function onAMac(ua: string = typeof navigator !== "undefined" ? navigator.userAgent : "",
                       touchPoints: number = typeof navigator !== "undefined" ? navigator.maxTouchPoints : 0): boolean {
  return /Macintosh/.test(ua) && touchPoints < 2;
}

/** The line under an app's row: ("granted", on a Mac) -> "Allowed"; ("denied", on a Mac) -> "Refused: allow Odie
 * under System Settings → Privacy & Security → Automation"; ("unknown", not on a Mac) -> "Allow this on the Mac". */
export function macAppLine(status: MacAppStatus, mac: boolean): string {
  if (status === "granted") return "Allowed";
  if (status === "denied") return mac ? "Refused: allow Odie under System Settings → Privacy & Security → Automation" : "Refused on the Mac";
  return mac ? "Not asked yet" : "Allow this on the Mac";
}
