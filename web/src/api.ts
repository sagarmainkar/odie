import { userLocale } from "./locale";
export async function getJSON<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
export async function postJSON<T>(url: string, body: unknown): Promise<T> {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
export async function putJSON<T>(url: string, body: unknown): Promise<T> {
  const r = await fetch(url, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
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
