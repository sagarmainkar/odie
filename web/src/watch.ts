/** The watch's card on Today (mail and calendar, checked every 30 minutes in the background) and its marker in chat. */
import { avatarColour, initialOf } from "./blocks/rowAvatar";
import type { IconName, TileColor } from "./components/Tile";
import { userLocale } from "./locale";
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
  if (failing.length) return failing.map((s) => `${s.app} (${s.kind}): ${s.reason ?? "not working"}`).join(" · ");
  if (!card.checked_at) return "";
  const apps = [...new Set(Object.values(card.sources ?? {}).map((s) => s.app))].join(", ");
  const due = new Date(card.checked_at).getTime() + 30 * 60_000;
  return `checked ${hm(card.checked_at)}${apps ? ` via ${apps}` : ""} · next ${due > now.getTime() ? plus30(card.checked_at) : "soon"}`;
}

export function badge(unseen: number): string {
  return unseen <= 0 ? "" : unseen > 9 ? "9+" : String(unseen);
}

export function chatAbout(item: WatchItem): string {
  return `Tell me about: ${item.title}`;
}

export type WatchRowView = {
  title: string;
  subtitle: string;  // block text: :badge[…] pills draw as in a chat row (InlineText)
  lead: { kind: "initial"; letter: string; colour: string } | { kind: "tile"; icon: IconName; color: TileColor };
  value: string;     // the mail's time, short
  run: string;       // what tapping the row asks the chat
};

/** "14:00" for a time today, the weekday ("Tue") for another day, "" when the time isn't ISO (another app's wording). */
export function whenShort(iso: string, today: string): string {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(iso)) return "";
  if (iso.slice(0, 10) === today) return iso.slice(11, 16);
  return new Date(iso).toLocaleDateString(userLocale(), { weekday: "short" });
}

/**
 * How a needs-you item shows on Today, the way the chat's mail rows look. Worked examples:
 *   a mail item from "Priya Nair", subject "Lease renewal", why "₹2,480 by the 10th", at 14:00 today, not yet seen
 *     -> "Priya Nair · Lease renewal", a "P" avatar, ":badge[New]{good} ₹2,480 by the 10th", "14:00",
 *        tap asks "Open the email from Priya Nair about Lease renewal (in <its app>, id <its id>)" (mailWhere)
 *   the same once Today has shown it, with no reason from the model -> the gist under it, no pill
 *   an item from before the watch kept the sender, or an event -> the model's title, a mail or calendar tile,
 *        tap asks "Tell me about: <title>"
 */
/**
 * Where a mail item's tap should look: the app that holds it and its id, so chat opens that mail instead of guessing
 * which app to search. Worked examples:
 *   ref "mail:18f3a2", app "Mail Connector"          -> " (in Mail Connector, id 18f3a2)"
 *   an older item without app, one badge "Apple Mail" -> " (in Apple Mail, id …)"
 *   no app and two badges (both apps had a copy)      -> " (id 18f3a2)": the id alone, since either app may hold it
 */
export function mailWhere(item: WatchItem): string {
  const id = item.ref.replace(/^mail:/, "");
  let app = item.app ?? "";
  if (!app && item.badges?.length === 1) app = item.badges[0].app;
  if (!app) return ` (id ${id})`;
  return ` (in ${app}, id ${id})`;
}

export function watchRow(item: WatchItem, today: string): WatchRowView {
  const pill = item.seen ? "" : ":badge[New]{good} ";
  if (item.from && item.subject) {
    return { title: `${item.from} · ${item.subject}`, subtitle: `${pill}${item.why || item.gist || ""}`.trim(),
             lead: { kind: "initial", letter: initialOf(item.from) ?? "?", colour: avatarColour(item.from) },
             value: whenShort(item.when ?? "", today), run: `Open the email from ${item.from} about ${item.subject}${mailWhere(item)}` };
  }
  const event = item.ref.startsWith("event:");
  return { title: item.title, subtitle: `${pill}${item.why}`.trim(),
           lead: { kind: "tile", icon: event ? "cal" : "mail", color: event ? "orange" : "blue" }, value: "", run: chatAbout(item) };
}
