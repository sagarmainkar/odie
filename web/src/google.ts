import { userLocale } from "./locale";
export type GoogleCheck = { gmail: string; calendar: string };
export const CONNECT_MARK = "[connect:google]";

const WORD: Record<string, string> = { ok: "Connected", expired: "Login expired", calendar: "Not granted", not_connected: "Not connected", error: "Couldn't check" };

/** One line per service for Settings, and the button that fixes the worst of them. */
export function googleRows(c: GoogleCheck | null, connected: boolean): { gmail: string; calendar: string; action: "Connect Google" | "Reconnect" | "Add Calendar" | null; ok: boolean } {
  if (!connected) return { gmail: "Not connected", calendar: "Not connected", action: "Connect Google", ok: false };
  if (!c) return { gmail: "Checking…", calendar: "Checking…", action: null, ok: true };
  const expired = c.gmail === "expired" || c.calendar === "expired";
  const action = expired || c.gmail === "not_connected" ? "Reconnect" : c.calendar === "calendar" || c.calendar === "not_connected" ? "Add Calendar" : null;
  return { gmail: WORD[c.gmail] ?? c.gmail, calendar: WORD[c.calendar] ?? c.calendar, action, ok: c.gmail === "ok" && c.calendar === "ok" };
}

/** "Renew by 12 Oct": Google's Testing apps log out 7 days after connecting. */
export function renewBy(connectedAt: string | null | undefined): string {
  if (!connectedAt) return "";
  const d = new Date(Date.parse(connectedAt) + 7 * 86400000);
  return `Logs out every 7 days (Google test app) · renew by ${d.toLocaleDateString(userLocale(), { day: "numeric", month: "short" })}`;
}

/** A message that asks for a Connect card: its text without the marker, and whether to show the card. */
export function splitConnect(text: string): { text: string; connect: boolean } {
  return text.includes(CONNECT_MARK) ? { text: text.replace(CONNECT_MARK, "").trim(), connect: true } : { text, connect: false };
}
