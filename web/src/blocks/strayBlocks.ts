// Small models sometimes write a block in a shape of their own instead of an ```odie-blocks fence (Gemma 4, chat of
// 12 Oct 2026), and the chat showed it raw:
//   ```odie-checklist                                    a fence named after the block's kind
//   {"title": "3-Day Ooty Trip", "items": [{"text": "Thermals", "group": "Warm Layers"}]}
//   ```
//   <callout tone="tip" title="Pro-Tip for Parents">     an HTML-like tag named after the block's kind
//   Ginger candy helps on the winding roads.
//   </callout>
// Before a reply is drawn, each becomes the ```odie-blocks fence it meant. Names the app doesn't draw are left as they
// are, and text inside any other fence is never touched.
import { readJson } from "./parse/lenientJson";
import { BLOCK_KINDS } from "./parse";

// Fences with readers of their own, which keep their names: ```odie-images (photos), ```odie-chart (a chart), and
// ```odie-blocks itself.
const OWN_FENCES = ["images", "chart", "blocks"];
// The kinds a tag can be read as, and the field its inner text goes to. Other kinds hold lists or numbers that a
// tag's text doesn't map onto, so a tag of theirs stays as it is.
const TAG_TEXT_FIELD: Record<string, string> = { callout: "text", heading: "text", text: "text", badge: "text", source: "text" };

// A line that opens or closes a fence, with what follows the backticks: "```odie-checklist" → "odie-checklist".
const FENCE_LINE = /^[ \t>]*```(.*)$/;
// A tag on lines of its own, from its start to its closing tag: <callout tone="tip">…</callout>.
const TAG = /^[ \t]*<([a-z]+)((?:\s+[\w-]+\s*=\s*(?:"[^"]*"|'[^']*'))*)\s*>([\s\S]*?)<\/\1>[ \t]*$/gm;
// One attribute of a tag: tone="tip" or title='Pro-Tip'.
const ATTRIBUTE = /([\w-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')/g;

/**
 * The reply with stray block fences and block tags turned into ```odie-blocks fences. Worked examples:
 *   '```odie-checklist\n{"items": ["Jacket"]}\n```'     → '```odie-blocks\n{"items":["Jacket"],"type":"checklist"}\n```'
 *   '```odie-table\n[{"columns": […], "rows": […]}]\n```' → each object without a type becomes a table
 *   '<callout tone="tip" title="Tip">Carry cash.</callout>'
 *     → '```odie-blocks\n[{"tone":"tip","title":"Tip","type":"callout","text":"Carry cash."}]\n```'
 *   '```odie-weather\n{…}\n```' and '<marquee>Hi</marquee>' → unchanged (not kinds the app draws)
 */
export function tidyStrayBlocks(text: string): string {
  if (!text.includes("```odie-") && !text.includes("</")) return text;
  const out: string[] = [];
  let outside: string[] = [];  // lines outside fences, read for tags together (a tag can span lines)
  const lines = text.split("\n");
  let i = 0;
  while (i < lines.length) {
    const opener = lines[i].match(FENCE_LINE);
    if (!opener) {
      outside.push(lines[i]);
      i += 1;
      continue;
    }
    out.push(...tagsAsFences(outside));
    outside = [];
    let end = i + 1;
    while (end < lines.length && !FENCE_LINE.test(lines[end])) end += 1;
    const body = lines.slice(i + 1, end);
    const closed = end < lines.length;
    const kind = strayKind(opener[1]);
    if (kind) {
      out.push(lines[i].replace(/```.*$/, "```odie-blocks"), ...withKind(body.join("\n"), kind).split("\n"));
    } else {
      out.push(lines[i], ...body);
    }
    if (closed) out.push(lines[end]);
    i = end + 1;
  }
  out.push(...tagsAsFences(outside));
  return out.join("\n");
}

/**
 * Decides whether a fence's name is a block kind written as its own fence, and which: "odie-checklist" → "checklist";
 * "odie-blocks", "odie-images", "odie-chart" → null (fences of their own); "odie-weather", "python" → null.
 */
function strayKind(name: string): string | null {
  const m = name.trim().match(/^odie-([a-z]+)$/);
  if (!m) return null;
  const kind = m[1];
  if (OWN_FENCES.includes(kind) || !BLOCK_KINDS.includes(kind)) return null;
  return kind;
}

/**
 * A stray fence's JSON with `kind` as the type of each block that has none: an object, or a list of them. JSON that
 * doesn't read yet (still streaming in, or broken) comes back as written, and the chat says it's drawing (or couldn't).
 *   ('{"items": ["Jacket"]}', "checklist")        → '{"items":["Jacket"],"type":"checklist"}'
 *   ('[{"type": "callout", "text": "x"}]', "list") → '[{"type":"callout","text":"x"}]'  (a type of its own is kept)
 *   ('{"items": ["Jack', "checklist")             → '{"items": ["Jack'                (not finished)
 */
function withKind(json: string, kind: string): string {
  const data = readJson(json);
  const typed = (v: unknown) => (v && typeof v === "object" && !Array.isArray(v) && !("type" in v) ? { ...v, type: kind } : v);
  if (Array.isArray(data)) return JSON.stringify(data.map(typed));
  if (data && typeof data === "object") return JSON.stringify(typed(data));
  return json;
}

/**
 * Lines outside fences with each block tag (on lines of its own) turned into an ```odie-blocks fence: its attributes
 * become fields, its inner text the kind's text field. No lines in, no lines out.
 *   '<callout tone="warn">Roads close at 6.</callout>' → '```odie-blocks\n[{"tone":"warn","type":"callout","text":"Roads close at 6."}]\n```'
 *   '<table><tr><td>1</td></tr></table>'               → unchanged (a table's rows don't come from its text)
 */
function tagsAsFences(lines: string[]): string[] {
  const text = lines.join("\n");
  if (!text.includes("</")) return lines;
  const tidy = text.replace(TAG, (whole: string, kind: string, attributes: string, inner: string) => {
    const field = TAG_TEXT_FIELD[kind];
    if (!field) return whole;
    const block: Record<string, string> = {};
    for (const a of attributes.matchAll(ATTRIBUTE)) block[a[1]] = a[2] ?? a[3];
    block.type = kind;
    block[field] = inner.trim();
    return "```odie-blocks\n" + JSON.stringify([block]) + "\n```";
  });
  return tidy.split("\n");
}
