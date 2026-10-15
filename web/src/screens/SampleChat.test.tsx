import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { loadSample } from "../blocks/eval/chats";
import { ReplyText } from "./Chat";

describe("the sample chat", () => {
  it("is there, with its turns, and every reply draws as blocks rather than raw fences", async () => {
    const chat = await loadSample();
    expect(chat).not.toBeNull();
    expect(chat!.turns.length).toBeGreaterThanOrEqual(8);
    for (const turn of chat!.turns) {
      const where = `turn ${turn.n}`;
      expect(turn.score.not_drawn, where).toEqual([]);
      expect(turn.error, where).toBeNull();
      const browserOnly = turn.score.kinds.some((k) => k === "images" || k === "diagram") || turn.reply.includes("```odie-images");
      if (browserOnly) continue;  // photos open in a portal and mermaid draws into the document: only a browser can
      const html = renderToStaticMarkup(<ReplyText text={turn.reply} />);
      expect(html, where).not.toContain("language-odie-blocks");
    }
    expect(chat!.turns.filter((t) => t.score.kinds.length > 0).length).toBeGreaterThanOrEqual(8);  // a sample that shows blocks
  });
});
