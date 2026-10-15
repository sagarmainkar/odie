/** Odie in a phone's browser, not the home-screen app: full screen, notifications and links work better from the icon. */
export function isStandalone(): boolean {
  return typeof window !== "undefined" && (window.matchMedia?.("(display-mode: standalone)").matches || (navigator as { standalone?: boolean }).standalone === true);
}

export function isPhone(ua: string = typeof navigator !== "undefined" ? navigator.userAgent : ""): boolean {
  return /iPhone|iPod|Android.*Mobile/i.test(ua);
}

export function shouldNudge({ standalone, phone, dismissed }: { standalone: boolean; phone: boolean; dismissed: boolean }): boolean {
  return phone && !standalone && !dismissed;
}

const KEY = "odie.installNudge.dismissed";

export function nudgeDismissed(): boolean {
  try { return localStorage.getItem(KEY) === "1"; } catch { return false; }
}

export function dismissNudge(): void {
  try { localStorage.setItem(KEY, "1"); } catch { /* private mode: it shows again next time */ }
}
