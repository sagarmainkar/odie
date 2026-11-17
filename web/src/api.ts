import { userLocale } from "./locale";
import { withPick } from "./pick";

// Every helper below names the picked personality on the calls that follow it (pick.ts: the chat, its history, the
// threads, the cards), so no screen can forget to.
export async function getJSON<T>(url: string): Promise<T> {
  const r = await fetch(withPick(url));
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
/** What a refused call says: the server's own words when it gave some, else the status.
 *    409 {"detail": "Mira's brain … isn't set up any more, …"} -> those words (a tap on her card: the card keeps waiting)
 *    500, no body; or a detail that isn't words              -> "HTTP 500" */
export function errorWords(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  return `HTTP ${status}`;
}
export async function postJSON<T>(url: string, body: unknown): Promise<T> {
  const r = await fetch(withPick(url), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(errorWords(r.status, await r.json().catch(() => null)));
  return r.json();
}
export async function putJSON<T>(url: string, body: unknown): Promise<T> {
  const r = await fetch(withPick(url), { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
export async function deleteJSON<T>(url: string): Promise<T> {
  const r = await fetch(withPick(url), { method: "DELETE" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
export function todayISO(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
export function urlBase64ToUint8Array(b64: string): Uint8Array {
  const pad = "=".repeat((4 - (b64.length % 4)) % 4);
  const raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}
export function speak(text: string, onStart?: () => void, onEnd?: () => void) {
  if (!("speechSynthesis" in window)) return false;
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text.replace(/[*_`#]/g, ""));
  u.rate = 1.02;
  const voices = window.speechSynthesis.getVoices();
  const lang = userLocale();
  const base = lang.split("-")[0];
  u.voice = voices.find((v) => v.lang.toLowerCase() === lang.toLowerCase())
    ?? (base === "en" ? voices.find((v) => /en-GB/i.test(v.lang)) : undefined)
    ?? voices.find((v) => v.lang.split("-")[0] === base) ?? null;
  u.onstart = () => onStart?.();
  u.onend = () => onEnd?.();
  u.onerror = () => onEnd?.();
  window.speechSynthesis.speak(u);
  return true;
}
export function dictate(onText: (t: string) => void, onEnd: () => void): (() => void) | null {
  const SR = (window as any).webkitSpeechRecognition || (window as any).SpeechRecognition;
  if (!SR) return null;
  const rec = new SR();
  rec.lang = userLocale(); rec.interimResults = true; rec.continuous = false;
  rec.onresult = (e: any) => { let t = ""; for (const r of e.results) t += r[0].transcript; onText(t); };
  rec.onend = onEnd; rec.onerror = onEnd;
  rec.start();
  return () => rec.stop();
}
