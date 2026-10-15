// Inline syntax inside text: small pills and icons a model can drop into any sentence, in block text fields and in
// normal reply Markdown. Hand-written (a regex over text), no library.
//
//   :badge[Best value]        a small pill; :badge[Sold out]{warn} or {good} colours it (any other word: a plain pill;
//                             braces holding more than a word: their text follows the pill, see braceAfterBadge)
//   :icon[plane]              one of the app's icons; an unknown name is dropped and the text around it kept
//   **bold**                  bold         } block text only: reply text already gets these from Markdown
//   [label](https://…)        a link       }
import { ICON_NAMES, type IconName } from "../components/Tile";

export type Piece =
  | { kind: "text"; text: string }
  | { kind: "badge"; text: string; tone?: "good" | "warn" }
  | { kind: "icon"; name: IconName }
  | { kind: "bold"; text: string }
  | { kind: "link"; text: string; url: string };

// One pattern per piece of syntax, each with its own capture groups.
const BADGE = String.raw`:badge\[([^\]\n]{1,40})\](?:\{([^{}\n]{1,60})\})?`;  // 1: text, 2: what's in the braces
const ICON = String.raw`:icon\[([\w-]{1,24})\]`;                          // 3: name
const BOLD = String.raw`\*\*([^*\n]{1,200})\*\*`;                         // 4: text
const LINK = String.raw`\[([^\]\n]{1,100})\]\((https:\/\/[^\s)]+)\)`;     // 5: label, 6: url

/** Badges and icons only (for reply Markdown); and everything (for block text). */
const DIRECTIVES = () => new RegExp(`${BADGE}|${ICON}`, "g");
const EVERYTHING = () => new RegExp(`${BADGE}|${ICON}|${BOLD}|${LINK}`, "g");

/**
 * Text → plain runs and inline pieces, in order.
 *   "Pixel :badge[Best]{good} :icon[nope]today"
 *   → [{text "Pixel "}, {badge "Best", tone good}, {text " today"}]   (the unknown icon is gone, its neighbours joined)
 * With markdown: false only badges and icons are read; **bold** and links stay as text for Markdown to handle.
 */
export function splitInline(text: string, { markdown = true }: { markdown?: boolean } = {}): Piece[] {
  const pieces: Piece[] = [];
  const pattern = markdown ? EVERYTHING() : DIRECTIVES();
  let last = 0;
  for (const m of text.matchAll(pattern)) {
    pushText(pieces, text.slice(last, m.index));
    last = m.index + m[0].length;
    for (const piece of piecesFor(m)) {
      if (piece.kind === "text") pushText(pieces, piece.text);
      else pieces.push(piece);
    }
  }
  pushText(pieces, text.slice(last));
  return pieces;
}

/** The pieces one regex match stands for (see the group numbers above); none for an icon the app doesn't have. */
function piecesFor(m: RegExpMatchArray): Piece[] {
  if (m[1] !== undefined) return badgePieces(m[1], m[2]);
  if (m[3] !== undefined) {
    const known = (ICON_NAMES as string[]).includes(m[3]);
    return known ? [{ kind: "icon", name: m[3] as IconName }] : [];
  }
  if (m[4] !== undefined) return [{ kind: "bold", text: m[4] }];
  return [{ kind: "link", text: m[5], url: m[6] }];
}

/**
 * A badge and what its braces held. One word is a colour: good and warn tint the pill, any other word is dropped (a
 * plain pill). Anything longer was meant to be read, so the braces go and their text follows the pill:
 *   ":badge[Best]{good}"           → [badge "Best", tone good]
 *   ":badge[Best]{blue}"           → [badge "Best"]
 *   ":badge[Best]{up to 5400 mAh}" → [badge "Best", text " up to 5400 mAh"]   (Gemma wrote this in a table cell)
 */
function badgePieces(text: string, braces: string | undefined): Piece[] {
  const word = braces?.trim() ?? "";
  if (braceIsToneWord(word)) return [{ kind: "badge", text: text.trim(), tone: badgeToneWord(word) }];
  return [{ kind: "badge", text: text.trim() }, { kind: "text", text: ` ${word}` }];
}

/** Whether braces after a badge hold a colour word (letters only, up to 12): "warn" → yes, "" → yes (no braces, no
 *  colour), "up to 5400 mAh" → no, "5400mAh" → no. */
function braceIsToneWord(word: string): boolean {
  return /^[a-z]{0,12}$/i.test(word);
}

function badgeToneWord(word: string | undefined): "good" | "warn" | undefined {
  if (word === "good") return "good";
  if (word === "warn") return "warn";
  return undefined;
}

/** Adds text, joining it to the text piece before it so dropped icons don't leave a run in two halves. */
function pushText(pieces: Piece[], text: string) {
  if (!text) return;
  const before = pieces[pieces.length - 1];
  if (before?.kind === "text") before.text += text;
  else pieces.push({ kind: "text", text });
}

/** The words a reader sees, without the syntax (for sorting and matching): ":badge[Best]{good} **Pixel**" → "Best Pixel". */
export function plainInline(text: string): string {
  const words: string[] = [];
  for (const p of splitInline(text)) {
    if (p.kind !== "icon") words.push(p.text);
  }
  return words.join("").trim();
}

// --- In reply Markdown: a remark plugin --------------------------------------------------------------------------
// remark parses the reply into a tree (mdast). This walks it and swaps each text node holding badges or icons for
// plain text nodes plus <span> elements the chat draws (see MarkdownSpan). Code and inline code are separate node
// types, so `:badge[x]` inside backticks is left as written.

type MdNode = { type: string; value?: string; children?: MdNode[]; data?: { hName?: string; hProperties?: Record<string, unknown> } };

export function remarkInline() {
  return (tree: MdNode) => swapTextNodes(tree);
}

function swapTextNodes(node: MdNode) {
  if (!node.children) return;
  const next: MdNode[] = [];
  for (const child of node.children) {
    if (child.type === "text" && child.value) {
      next.push(...textToNodes(child.value));
    } else {
      swapTextNodes(child);
      next.push(child);
    }
  }
  node.children = next;
}

/** "Go :badge[Now]{good}" → [text "Go ", <span class="chip chip-inline chip-good">Now</span>] */
function textToNodes(value: string): MdNode[] {
  return splitInline(value, { markdown: false }).map((p): MdNode => {
    if (p.kind === "badge") {
      const className = ["chip", "chip-inline", badgeClass(p.tone)];
      return { type: "odieBadge", data: { hName: "span", hProperties: { className } }, children: [{ type: "text", value: p.text }] };
    }
    if (p.kind === "icon") {
      return { type: "odieIcon", data: { hName: "span", hProperties: { className: ["inline-icon"], dataIcon: p.name } }, children: [] };
    }
    if (p.kind === "text") return { type: "text", value: p.text };
    return { type: "text", value: "" };  // bold and links never come back with markdown: false; Markdown draws them
  });
}

/** The chip class for a badge tone: good and warn are tinted, no tone is a soft grey. */
export function badgeClass(tone: "good" | "warn" | undefined): string {
  if (tone === "good") return "chip-good";
  if (tone === "warn") return "chip-warn";
  return "chip-soft";
}
