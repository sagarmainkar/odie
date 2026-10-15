// Scoring one reply of a replayed (or imported) chat, for the chat replay (scripts/chat_replay.sh). A chat turn has no
// "expected" blocks, so this only says what the chat drew and what it didn't: it reads the reply with the same Markdown
// parser the chat uses (remark with GFM, as react-markdown runs it, after the chat's tidyStrayBlocks), asks fenceShown.ts how the chat shows each fence,
// and reads each blocks fence with the app's own block parser, so a fence the owner saw as raw JSON shows up here too.
import remarkGfm from "remark-gfm";
import remarkParse from "remark-parse";
import { unified } from "unified";
import { plainMath } from "../../plainMath";
import { howChatShowsFence } from "../fenceShown";
import { tidyStrayBlocks } from "../strayBlocks";
import { readBlocks, type Diagnostic } from "../parse";
import { kindsOf } from "./score";

/** Something in a reply that looks like it was meant to be drawn but isn't. `as`: how the chat shows it instead. */
export type NotDrawn = { as: "code box" | "inline code" | "text" | "stuck placeholder" | "couldn't draw"; lang: string; text: string };

export type ChatReplyScore = {
  fences: number;          // odie-* fences (and json fences the chat draws), read as Markdown reads them
  parsed: boolean;         // every one of them was read (none broken, none stuck)
  kinds: string[];         // every kind drawn, containers and their children included, in order ("images", "chart" too)
  dropped: Diagnostic[];   // what the block parser dropped, prefixed with the fence number ("f1:0.rows.2")
  not_drawn: NotDrawn[];   // fence-looking text the chat did NOT draw
};

type MdNode = { type: string; lang?: string | null; value?: string; children?: MdNode[] };

const SNIPPET = 90;  // characters of a not-drawn piece kept, to recognise it by

/** The parts of a reply's Markdown tree that matter here, in order: fences, inline code and plain text. */
function walk(node: MdNode, out: MdNode[]) {
  if (node.type === "code" || node.type === "inlineCode" || node.type === "text") out.push(node);
  for (const child of node.children ?? []) walk(child, out);
}

/**
 * Decides whether a piece of inline code or text looks like a fence or block JSON the model meant the chat to draw.
 *   "odie-images: {\"images\": […]}" (a one-line ```odie-images … ``` read as inline code) → true
 *   "{\"type\": \"table\", \"rows\": […]}"                                                  → true
 *   "Here's your plan for Ooty"                                                            → false
 *   "npm ci"                                                                               → false
 */
export function looksLikeAFence(text: string): boolean {
  if (/odie-(blocks|images|chart)/.test(text)) return true;
  if (text.includes("```")) return true;
  return /^\s*[[{]\s*"(type|images|title)"/.test(text);
}

/** A short piece of text to recognise something by: "{"type": "table", "title": …" (90 characters at most). */
function snippet(text: string): string {
  const one = text.replace(/\s+/g, " ").trim();
  if (one.length <= SNIPPET) return one;
  return one.slice(0, SNIPPET) + "…";
}

/**
 * Scores one reply. Worked examples:
 *   "Here:\n```odie-blocks\n[{\"type\":\"divider\"}]\n```" → 1 fence, parsed, kinds ["divider"], nothing not drawn
 *   "```odie-images: {\"images\": […]} ```" (all on one line)  → 0 fences, not drawn [{as: "inline code", …}]
 *   "```odie-blocks\n{\"type\": \"table\" …" (never closed, cut off) → 1 fence, not parsed, [{as: "stuck placeholder"}]
 *   "Just words."                                               → 0 fences, parsed, nothing drawn, nothing not drawn
 */
export function scoreChatReply(text: string): ChatReplyScore {
  const markdown = unified().use(remarkParse).use(remarkGfm);  // what react-markdown runs, with the chat's remarkGfm
  const tree = markdown.runSync(markdown.parse(plainMath(tidyStrayBlocks(text)))) as MdNode;
  const nodes: MdNode[] = [];
  walk(tree, nodes);

  let fences = 0;
  let parsed = true;
  const kinds: string[] = [];
  const dropped: Diagnostic[] = [];
  const notDrawn: NotDrawn[] = [];
  for (const node of nodes) {
    const value = node.value ?? "";
    if (node.type === "code") {
      const lang = node.lang ?? "";
      const shown = howChatShowsFence(lang, value);
      const meantToDraw = lang.startsWith("odie") || looksLikeAFence(value);
      if (shown.as === "blocks") {
        fences += 1;
        const read = readBlocks(value);
        kinds.push(...kindsOf(shown.blocks));
        for (const d of read?.dropped ?? []) dropped.push({ path: `f${fences}:${d.path}`, why: d.why });
      } else if (shown.as === "images" || shown.as === "chart" || shown.as === "diagram" || shown.as === "svg") {
        fences += 1;
        kinds.push(shown.as);
      } else if (shown.as === "waiting") {
        fences += 1;
        parsed = false;
        notDrawn.push({ as: "stuck placeholder", lang, text: snippet(value) });
      } else if (shown.as === "broken") {
        fences += 1;
        parsed = false;
        notDrawn.push({ as: "couldn't draw", lang, text: snippet(value) });
      } else if (meantToDraw) {
        notDrawn.push({ as: "code box", lang, text: snippet(value) });
      }
    } else if (looksLikeAFence(value)) {
      notDrawn.push({ as: node.type === "inlineCode" ? "inline code" : "text", lang: "", text: snippet(value) });
    }
  }
  return { fences, parsed, kinds, dropped, not_drawn: notDrawn };
}
