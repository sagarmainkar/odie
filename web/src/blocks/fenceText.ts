import { plainInline } from "./inlineSyntax";

// Fields that say how to draw or what to do, not what to read: left out of the text version.
const SKIP_KEYS = ["type", "kind", "icon", "image", "url", "src", "href", "run", "ask", "tone", "variant", "collapsed",
  "ranked", "numbered", "ordered", "highlight", "done", "checked", "today", "change_unit", "fence",
  "id", "formula", "step"];

/**
 * A fence the app couldn't draw, as lines a person can read: each object's text and numbers on one line, what it holds
 * on the lines below. When the text isn't JSON, it comes back as written.
 *   '[{"type":"timeline","groups":[{"label":"Day 1","items":[{"time":"09:00","title":"Fushimi Inari"}]}]}]'
 *   → "Day 1\n09:00 · Fushimi Inari"
 */
export function fenceAsText(code: string): string {
  let data: unknown;
  try {
    data = JSON.parse(code);
  } catch {
    return code;
  }
  const lines: string[] = [];
  collectLines(data, lines);
  return lines.join("\n");
}

function collectLines(value: unknown, lines: string[]) {
  if (Array.isArray(value)) {
    for (const v of value) collectLines(v, lines);
    return;
  }
  if (value && typeof value === "object") {
    const words: string[] = [];
    const nested: unknown[] = [];
    for (const [key, v] of Object.entries(value)) {
      if (SKIP_KEYS.includes(key)) continue;
      if (typeof v === "string" && v.trim()) words.push(plainInline(v));
      else if (typeof v === "number") words.push(String(v));
      else if (v && typeof v === "object") nested.push(v);
    }
    if (words.length) lines.push(words.join(" · "));
    for (const v of nested) collectLines(v, lines);
    return;
  }
  if (typeof value === "string" && value.trim()) lines.push(plainInline(value));
  if (typeof value === "number") lines.push(String(value));
}
