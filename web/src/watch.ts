/** The watch's last check (mail and calendar, every 30 minutes in the background): the line under Today's "Needs
 * you", and the count on chat's way back to Today. */
export type WatchItem = {
  ref: string; title: string; why: string; at: string; done?: boolean; seen?: boolean;
  from?: string; subject?: string; when?: string; gist?: string;  // a mail item: the mail behind it (odie.watch.report)
  badges?: { kind: string; app: string }[];  // where it came from: Gmail, iCloud, another app
  app?: string;  // the app that holds the mail's id (the ref), so a tap can open it there
};
export type WatchCardData = {
  checked_at?: string; line?: string; needs_you: WatchItem[];
  events: { id: string; title: string; start: string; where?: string }[];
  sources?: Record<string, { ok: boolean; app: string; kind: string; reason?: string }>; off?: string; unseen: number;
};

/** "HH:MM" of an ISO time, as written (the user's own clock: the server writes local times). */
const hm = (iso: string) => iso.slice(11, 16);

function plus30(iso: string): string {
  const [h, m] = hm(iso).split(":").map(Number);
  const t = (h * 60 + m + 30) % (24 * 60);
  return `${String(Math.floor(t / 60)).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`;
}

export function footer(card: WatchCardData, now: Date): string {
  const failing = Object.values(card.sources ?? {}).filter((s) => !s.ok);
  // The raw error stays in Settings: "Calendar" (calendar) -> "Calendar isn't working"; "Zapier" (mail) -> "Zapier (mail) isn't working".
  const name = (s: { app: string; kind: string }) => (s.app.toLowerCase().includes(s.kind) ? s.app : `${s.app} (${s.kind})`);
  if (failing.length) return failing.map((s) => `${name(s)} isn't working`).join(" · ");
  if (!card.checked_at) return "";
  const apps = [...new Set(Object.values(card.sources ?? {}).map((s) => s.app))].join(", ");
  const due = new Date(card.checked_at).getTime() + 30 * 60_000;
  return `checked ${hm(card.checked_at)}${apps ? ` via ${apps}` : ""} · next ${due > now.getTime() ? plus30(card.checked_at) : "soon"}`;
}

export function badge(unseen: number): string {
  return unseen <= 0 ? "" : unseen > 9 ? "9+" : String(unseen);
}
