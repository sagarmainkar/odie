import { describe, expect, it } from "vitest";
import gemma from "./testdata/gemma-2026-10-12.json";
import { scoreChatReply } from "./eval/chatScore";
import { howChatShowsFence } from "./fenceShown";
import { tidyStrayBlocks } from "./strayBlocks";

/** Every fence of a reply as [language, text], in order. */
function fences(text: string): [string, string][] {
  return [...text.matchAll(/^```(\S*)\n([\s\S]*?)\n```$/gm)].map((m) => [m[1], m[2]]);
}

describe("stray block fences and tags", () => {
  it("draws Gemma's packing list: its ```odie-checklist fence and its <callout> tag (12 Oct 2026)", () => {
    const tidy = tidyStrayBlocks(gemma.packing);
    const [checklist, callout] = fences(tidy);
    expect(checklist[0]).toBe("odie-blocks");
    expect(callout[0]).toBe("odie-blocks");

    const list = howChatShowsFence(...checklist);
    expect(list.as).toBe("blocks");
    if (list.as !== "blocks") return;
    expect(list.blocks[0]).toMatchObject({ type: "checklist", title: "3-Day Ooty Trip (December)" });
    expect(list.blocks[0].type === "checklist" && list.blocks[0].items).toHaveLength(12);

    const tip = howChatShowsFence(...callout);
    expect(tip.as).toBe("blocks");
    if (tip.as !== "blocks") return;
    expect(tip.blocks[0]).toMatchObject({ type: "callout", tone: "tip", title: "Pro-Tip for Parents" });
    expect(tip.blocks[0].type === "callout" && tip.blocks[0].text).toMatch(/^The winding mountain roads/);

    expect(tidy).toContain("Ooty in December can be quite chilly");  // the words around them stay
    expect(tidy).not.toContain("<callout");
    expect(scoreChatReply(gemma.packing)).toMatchObject({ fences: 2, parsed: true, kinds: ["checklist", "callout"], not_drawn: [] });
  });

  it("leaves a reply without stray blocks as it is (Gemma's Markdown table of phones)", () => {
    expect(tidyStrayBlocks(gemma.phones)).toBe(gemma.phones);
  });

  it("gives each object of a list the fence's kind, and keeps a type the model gave", () => {
    const text = '```odie-callout\n[{"text": "Carry cash"}, {"type": "badge", "text": "New"}]\n```';
    const [[lang, body]] = fences(tidyStrayBlocks(text));
    expect(lang).toBe("odie-blocks");
    expect(JSON.parse(body)).toEqual([{ text: "Carry cash", type: "callout" }, { type: "badge", text: "New" }]);
  });

  it("keeps an unfinished stray fence's text as written, so it shows as drawing until it's complete", () => {
    const text = '```odie-checklist\n{"items": ["Jack';
    expect(tidyStrayBlocks(text)).toBe('```odie-blocks\n{"items": ["Jack');
    expect(howChatShowsFence("odie-blocks", '{"items": ["Jack').as).toBe("waiting");
  });

  it("leaves names the app doesn't draw, and fences with their own readers, untouched", () => {
    const unknown = '```odie-weather\n{"city": "Ooty"}\n```\n\n<marquee title="x">Hello</marquee>';
    expect(tidyStrayBlocks(unknown)).toBe(unknown);
    const own = '```odie-images\n{"images": []}\n```\n```odie-chart\n{"type": "bar"}\n```';
    expect(tidyStrayBlocks(own)).toBe(own);
    const tableTag = "<table>\n<tr><td>1</td></tr>\n</table>";  // a kind whose fields don't come from text
    expect(tidyStrayBlocks(tableTag)).toBe(tableTag);
  });

  it("never reads a tag inside another fence, or one in the middle of a sentence", () => {
    const inCode = '```html\n<callout tone="tip">Not a block</callout>\n```';
    expect(tidyStrayBlocks(inCode)).toBe(inCode);
    const inline = 'Write <callout>tip</callout> in your notes.';
    expect(tidyStrayBlocks(inline)).toBe(inline);
  });
});
