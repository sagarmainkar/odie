/** Handing a reply or a made file to another app: WhatsApp, Messages, Mail, AirDrop. A file can leave a web app only
 * through the phone's share sheet (navigator.share with files), where WhatsApp sits one tap away; words can go
 * straight into WhatsApp through its app link. Nothing here needs the server. */
import type { Media } from "./media";
import { mediaUrl } from "./media";

/** What the browser offers, as the components read it. share: the sheet exists (iPhone, iPad, Android, Safari on a
 * Mac); files: the sheet takes files (needs canShare); phone: WhatsApp's app link opens the app for sure. */
export type Sharer = {
  share?: (data: { title?: string; text?: string; files?: File[] }) => Promise<void>;
  canShare?: (data: { files?: File[] }) => boolean;
};

export type ShareOutcome = "shared" | "cancelled" | "unsupported" | "failed";

/** Decides whether the share sheet exists here: iPhone Safari (share on navigator) -> true; Firefox on a Mac -> false. */
export function canShareHere(nav: Sharer = typeof navigator !== "undefined" ? (navigator as Sharer) : {}): boolean {
  return typeof nav.share === "function";
}

/** WhatsApp with the words ready to send; the person picks the chat there.
 *  "Three colleges offer it." -> "whatsapp://send?text=Three%20colleges%20offer%20it." */
export function whatsappLink(text: string): string {
  return "whatsapp://send?text=" + encodeURIComponent(text);
}

/** A reply's words as they read in a chat app: fenced blocks (a chart's JSON, code) left out, headings and emphasis
 * marks dropped, a link kept as its words, a picture dropped, runs of blank lines closed up.
 *  "## Colleges\n\n- **COEP** — Pune\n\n```chart\n{}\n```\n\nSee [the list](https://x.y)." -> "Colleges\n\n- COEP — Pune\n\nSee the list." */
export function shareWords(markdown: string): string {
  const withoutBlocks = markdown.replace(/```[\s\S]*?(```|$)/g, "");
  const lines = withoutBlocks.split("\n").map((line) => line
    .replace(/^#{1,6}\s+/, "")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, "")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/(\*\*|__)(.+?)\1/g, "$2")
    .replace(/(^|[^*\w])[*_]([^*_\n]+?)[*_](?=[^*\w]|$)/g, "$1$2")
    .replace(/`([^`]+)`/g, "$1")
    .trimEnd());
  return lines.join("\n").replace(/\n{3,}/g, "\n\n").trim();
}

/** Why a share did not happen, from what the browser threw: the person closed the sheet -> "cancelled"; anything
 * else -> "failed". */
function outcomeOf(error: unknown): ShareOutcome {
  const name = (error as { name?: string } | null)?.name;
  return name === "AbortError" ? "cancelled" : "failed";
}

/** The sheet with words: "shared" once handed over, "cancelled" when the sheet was closed, "unsupported" without a sheet. */
export async function shareText(text: string, title?: string, nav: Sharer = typeof navigator !== "undefined" ? (navigator as Sharer) : {}): Promise<ShareOutcome> {
  if (typeof nav.share !== "function") return "unsupported";
  try {
    await nav.share({ title, text });
    return "shared";
  } catch (error) {
    return outcomeOf(error);
  }
}

/** The file a tool made, named as the download names it, with the type the server serves it as. */
export type ShareableFile = Pick<Media, "id"> & { filename?: string; title?: string };

/** Fetches a made file and hands it to the sheet. "unsupported" when the sheet can't take files (an older browser,
 * or none), "failed" when the file can't be fetched, "cancelled" when the sheet was closed.
 *  a deck PDF on an iPhone -> "shared" (WhatsApp, Messages, Mail or Files, the person's pick) */
export async function shareFile(file: ShareableFile, deps: { nav?: Sharer; fetch?: typeof fetch } = {}): Promise<ShareOutcome> {
  const nav = deps.nav ?? (typeof navigator !== "undefined" ? (navigator as Sharer) : {});
  const get = deps.fetch ?? fetch;
  if (typeof nav.share !== "function" || typeof nav.canShare !== "function") return "unsupported";
  const name = file.filename || file.title || "file";
  let made: File;
  try {
    const response = await get(mediaUrl(file));
    if (!response.ok) return "failed";
    const blob = await response.blob();
    made = new File([blob], name, { type: blob.type });
  } catch {
    return "failed";
  }
  if (!nav.canShare({ files: [made] })) return "unsupported";
  try {
    await nav.share({ files: [made], title: name });
    return "shared";
  } catch (error) {
    return outcomeOf(error);
  }
}
