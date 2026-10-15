/** Signed-in browsing (odie/signin): the disclaimer, and the live view's arithmetic — a tap on the shown frame mapped
 * to the page's CSS pixels, the phone's keyboard as messages, and a UPI app link from an Android intent link. */

export type SignIn = {
  on: boolean; accepted_at: string | null; accepted_version: number | null; terms_changed?: boolean;
  version: number; disclaimer: string; upi_id: string | null;
};
export type Site = { domain: string; since: string; last_used?: string | null };
export type Point = { x: number; y: number };
export type Box = { left: number; top: number; width: number; height: number };
export type LiveMsg =
  | { t: "tap"; x: number; y: number } | { t: "drag"; x0: number; y0: number; x1: number; y1: number }
  | { t: "text"; s: string } | { t: "key"; k: "Backspace" | "Enter" | "Tab" } | { t: "back" } | { t: "reload" } | { t: "go"; url: string };

/** The Turn on button: the box ticked, on the disclaimer the server shows now. */
export function canTurnOn(ticked: boolean, shownVersion: number | undefined, currentVersion: number | undefined): boolean {
  return ticked && shownVersion !== undefined && shownVersion === currentVersion;
}

export function sinceText(iso: string | null | undefined, locale?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString(locale, { day: "numeric", month: "short" });
}

/** A point on the shown frame (an <img> with object-fit: contain, so letterboxed) in the page's CSS pixels; null on the
 * bars. `box` is the image's on-screen box (getBoundingClientRect, so a zoomed image works too); `page` the page's size
 * in CSS pixels, whatever the frame's own pixels. */
export function toPage(p: Point, box: Box, page: { w: number; h: number }, clamp = false): Point | null {
  if (!(page.w > 0 && page.h > 0 && box.width > 0 && box.height > 0)) return null;
  const scale = Math.min(box.width / page.w, box.height / page.h);
  const left = box.left + (box.width - page.w * scale) / 2;
  const top = box.top + (box.height - page.h * scale) / 2;
  let x = (p.x - left) / scale, y = (p.y - top) / scale;
  if (x < 0 || y < 0 || x > page.w || y > page.h) {
    if (!clamp) return null;
    x = Math.min(Math.max(x, 0), page.w); y = Math.min(Math.max(y, 0), page.h);  // a drag that ends past the frame
  }
  return { x: Math.round(x * 10) / 10, y: Math.round(y * 10) / 10 };
}

const SLOP = 10;  // CSS pixels a finger may wander and still tap

/** From where the finger went down to where it came up (both in page pixels): a tap, or a drag (a scroll). */
export function gesture(down: Point, up: Point): LiveMsg {
  return Math.hypot(up.x - down.x, up.y - down.y) < SLOP ? { t: "tap", x: down.x, y: down.y }
    : { t: "drag", x0: down.x, y0: down.y, x1: up.x, y1: up.y };
}

/** The phone's keyboard, from a hidden field's beforeinput: text as text; Backspace and Enter as keys. While the
 * keyboard is composing (predictive text), nothing: compositionend sends the word. */
export function fromBeforeInput(inputType: string, data: string | null, transferred: string | null = null): LiveMsg | null {
  if (inputType === "insertCompositionText") return null;
  if (inputType === "deleteContentBackward") return { t: "key", k: "Backspace" };
  if (inputType === "insertLineBreak" || inputType === "insertParagraph") return { t: "key", k: "Enter" };
  const text = data ?? transferred;  // a paste or an AutoFill carries its text in dataTransfer, not in data
  if (inputType.startsWith("insert") && text) return { t: "text", s: text };
  return null;
}

/** Keys that don't arrive as beforeinput everywhere. */
export function fromKey(key: string): LiveMsg | null {
  return key === "Enter" || key === "Tab" ? { t: "key", k: key } : null;
}

/** A UPI app link, from a upi:// link or an Android intent:// link that carries one (as odie/browser/engine.py). */
export function upiLink(url: string): string | null {
  if (/^upi:\/\//i.test(url)) return url;
  const m = /^intent:\/\/([^#]*)#Intent;(.*)$/i.exec(url);
  if (m && /(^|;)scheme=upi(;|$)/i.test(m[2])) return `upi://${m[1]}`;
  return null;
}

/** Who gets paid and how much, from a UPI link (for the Pay card). */
export function upiDetails(url: string): { payee: string; amount: string } {
  const q = /^upi:\/\/[^?]*\?(.*)$/i.exec(url);
  if (!q) return { payee: "", amount: "" };
  const p = new URLSearchParams(q[1]);
  return { payee: p.get("pn") || p.get("pa") || "", amount: p.get("am") || "" };
}

export function signedInLine(site: string, done: boolean): string {
  return done ? `I'm signed in to ${site}.` : `I didn't sign in to ${site}.`;
}

export function liveUrl(tab: string, loc: { protocol: string; host: string }): string {
  return `${loc.protocol === "https:" ? "wss:" : "ws:"}//${loc.host}/api/browser/live/${encodeURIComponent(tab)}`;
}

/** Chat sends this line as if typed (Chat listens for odie:send). */
export function sendInChat(text: string): void {
  window.dispatchEvent(new CustomEvent("odie:send", { detail: text }));
}

/** A private chat's reply (it read a signed-in page) holds its web images until a tap: an image address can carry
 * what the model read. The tap's words name where they'd be fetched from. */
export function heldLabel(urls: string[]): string {
  const hosts = [...new Set(urls.map((u) => { try { return new URL(u).host.replace(/^www\./, ""); } catch { return ""; } }).filter(Boolean))];
  if (urls.length === 1) return `Show the image from ${hosts[0] ?? "the web"}`;
  const named = hosts.slice(0, 2).join(", ");
  return `Show ${urls.length} images from ${named}${hosts.length > 2 ? ` and ${hosts.length - 2} more` : ""}`;
}

export type LoginStatus = "signed_in" | "code" | "captcha" | "failed" | "wrong_site" | "expired" | "vault";
export type TurnState = "done" | "code" | "failed" | "captcha" | "vault";
export type SavedLogin = { site: string; username: string; saved_at: string; last_used: string | null };

/** What the sign-in box says after Odie's browser tried (odie/signin/box.py). */
export function loginStatusText(status: LoginStatus, site: string): string {
  switch (status) {
    case "signed_in": return `Signed in to ${site}.`;
    case "code": return `Enter the code ${site} sent you.`;
    case "captcha": return `${site} wants a check only you can do.`;
    case "failed": return "That didn't work: check the username and the password.";
    case "wrong_site": return `The page isn't on ${site} any more.`;
    case "expired": return "That took too long: sign in again.";
    case "vault": return "Odie couldn't open its vault on the Mac.";
  }
}

/** The "your turn" card's title, by its state (odie/agent/tools/browser.py). */
export function turnTitle(state: TurnState | undefined, site: string, auto: boolean): string {
  switch (state) {
    case "done": return auto ? `Signed in to ${site} with your saved login` : `Signed in to ${site}`;
    case "failed": return "The saved password didn't work";
    case "code": return `${site} sent you a code`;
    case "captcha": return `${site} wants a check only you can do`;
    case "vault": return "Odie couldn't open its vault on the Mac";
    default: return `${site} needs you to sign in`;
  }
}

export function offConfirm(saved: number): string {
  return saved ? `Turn off signed-in browsing? Odie signs out of every site and forgets ${saved} saved login${saved === 1 ? "" : "s"}.`
    : "Turn off signed-in browsing? Odie signs out of every site first.";
}
