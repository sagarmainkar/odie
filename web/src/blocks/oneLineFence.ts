// Small models sometimes write a whole fence on one line, the way a rule showed it to them (Gemma 4, 11 Oct 2026):
//   Text ```odie-images: {"title": "Coorg in October", "images": [{"url": "https://…"}]} ```
// Markdown can't open a fence there, so it drew the JSON as inline code. Before a reply is drawn, each such run is
// lifted onto lines of its own as a real fence. An opening line with the JSON already on it ("```odie-blocks: [{…")
// gets its JSON moved to the next line too. Text inside real fences is never touched.

const KINDS = "odie-images|odie-blocks|odie-chart";
// ```kind, an optional colon, JSON starting with { or [ and ending with } or ], then ``` (all on one line).
const ONE_LINE = new RegExp("```(" + KINDS + "):?[ \\t]*([[{].*?[\\]}])[ \\t]*```", "g");
// A fence opening at the start of a line with the JSON straight after it: ```odie-blocks: [{"type": …
const OPENER_WITH_JSON = new RegExp("^([ \\t]*)```(" + KINDS + "):?[ \\t]*([[{].*)$");
// Any line that opens or closes a fence.
const FENCE_LINE = /^[ \t>]*```/;

/**
 * The reply with one-line fences lifted into real ones.
 *   'Lovely!\n```odie-images: {"images": [{"url": "https://x"}]} ```\nMore'
 *   → 'Lovely!\n```odie-images\n{"images": [{"url": "https://x"}]}\n```\nMore'
 * A reply without "```odie-" comes back as it is.
 */
export function liftOneLineFences(text: string): string {
  if (!text.includes("```odie-")) return text;
  const out: string[] = [];
  let inFence = false;
  for (const line of text.split("\n")) {
    if (inFence) {
      if (FENCE_LINE.test(line)) inFence = false;
      out.push(line);
      continue;
    }
    if (hasOneLineFence(line)) {
      out.push(liftLine(line));
      continue;
    }
    const opener = line.match(OPENER_WITH_JSON);
    if (opener) {
      const [, indent, kind, json] = opener;
      out.push(`${indent}\`\`\`${kind}`, `${indent}${json}`);
      inFence = true;
      continue;
    }
    if (FENCE_LINE.test(line)) inFence = true;
    out.push(line);
  }
  return out.join("\n");
}

/** Whether a line holds a whole fence: '```odie-images {"images": […]} ```' → yes; '```odie-images' → no. */
function hasOneLineFence(line: string): boolean {
  ONE_LINE.lastIndex = 0;
  return ONE_LINE.test(line);
}

/** One line with its one-line fences put on lines of their own, the text around them kept before and after. */
function liftLine(line: string): string {
  const lifted = line.replace(ONE_LINE, (_whole, kind: string, json: string) => `\n\`\`\`${kind}\n${json}\n\`\`\`\n`);
  const withoutLeadingBreak = lifted.startsWith("\n") ? lifted.slice(1) : lifted;
  const withoutTrailingBreak = withoutLeadingBreak.endsWith("\n") ? withoutLeadingBreak.slice(0, -1) : withoutLeadingBreak;
  return withoutTrailingBreak;
}
