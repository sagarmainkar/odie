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

/** How many pictures go with one reply at most; the rest of a long reply's pieces stay in the words. */
export const MAX_PICTURES = 6;
/** A drawn piece shorter than this (a line of source links, a one-row note) is not worth a picture of its own. */
export const SMALL_PIECE = 90;

/** The visual pieces of a reply's bubble, in order: block fences, charts, diagrams, SVGs and tables (each marked
 * data-visual where it is drawn), leaving out pieces shorter than `minHeight` on screen and anything past the
 * first MAX_PICTURES. A bubble of words alone -> []. */
export function visualsIn(bubble: ParentNode | null, minHeight = 0): HTMLElement[] {
  if (!bubble) return [];
  const pieces = Array.from(bubble.querySelectorAll<HTMLElement>("[data-visual]"));
  const tall = pieces.filter((piece) => minHeight <= 0 || piece.getBoundingClientRect().height >= minHeight);
  return tall.slice(0, MAX_PICTURES);
}

/** The file name a reply's n-th picture goes out under: ("Odie", 0) -> "odie-1.png". */
export function pictureName(name: string, n: number): string {
  const base = name.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "odie";
  return `${base}-${n + 1}.png`;
}

/** Decides whether the share sheet exists here: iPhone Safari (share on navigator) -> true; Firefox on a Mac -> false. */
export function canShareHere(nav: Sharer = typeof navigator !== "undefined" ? (navigator as Sharer) : {}): boolean {
  return typeof nav.share === "function";
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

/** What became of a reply's pictures: "pictures" when they went, else why the words went alone. */
export type ReplyShared = { outcome: ShareOutcome; pictures: number; why?: string };

/** A reply to the sheet: its words, and its visual pieces as pictures when the sheet takes files. `render` draws
 * one piece (renderPicture); a piece that can't be drawn is left out, and the reason kept. Pictures first with
 * the words as their caption; words alone where files can't go (an older sheet), or when nothing could be drawn.
 *  a reply with a chart on an iPhone -> share({files: [chart.png], text, title}) -> {shared, 1 picture}
 *  the same on a sheet without canShare -> share({text, title}) -> {shared, 0, why "this browser's sheet can't take files"} */
export async function shareReply(reply: { text: string; title?: string; visuals: HTMLElement[]; name: string },
                                 render: (piece: HTMLElement, name: string, fileName: string) => Promise<{ file: File | null; why?: string }>,
                                 nav: Sharer = typeof navigator !== "undefined" ? (navigator as Sharer) : {}): Promise<ReplyShared> {
  if (typeof nav.share !== "function") return { outcome: "unsupported", pictures: 0 };
  let files: File[] = [];
  let why: string | undefined;
  if (reply.visuals.length) {
    if (typeof nav.canShare !== "function") {
      why = "this browser's sheet can't take files";
    } else {
      const drawn = await Promise.all(reply.visuals.map((piece, n) => render(piece, reply.name, pictureName(reply.name, n))));
      files = drawn.map((d) => d.file).filter((file): file is File => file !== null);
      why = drawn.find((d) => d.why)?.why;
      if (files.length && !nav.canShare({ files })) {
        files = [];
        why = "this browser's sheet can't take files";
      }
    }
  }
  try {
    await nav.share(files.length ? { files, text: reply.text, title: reply.title } : { text: reply.text, title: reply.title });
    return files.length ? { outcome: "shared", pictures: files.length } : { outcome: "shared", pictures: 0, why };
  } catch (error) {
    return { outcome: outcomeOf(error), pictures: files.length, why };
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
