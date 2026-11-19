import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Digest } from "../digest";
import { DigestCard } from "./DigestCard";
import { QuietList } from "./QuietList";

const evening: Digest = {
  kind: "evening", title: "This evening", text: "One thing needs you: the reply to Asha.", at: "2026-11-19T19:30:00+05:30",
  quiet: [{ id: 9, title: "Acme weekly digest" }], held: ["Gas bill"],
  changes: [{ id: 1, words: "Merged “Call about the deck” into “Send the deck”" }],
};

describe("the digest on Pulse", () => {
  it("shows its words, the digest lines with Done, what was held back and the review's changes with Undo", () => {
    const html = renderToStaticMarkup(<DigestCard initial={evening} />);
    expect(html).toContain("This evening");
    expect(html).toContain("One thing needs you: the reply to Asha.");
    expect(html).toContain("Acme weekly digest");
    expect(html).toContain(">Done</button>");
    expect(html).toContain("Held back from your phone: Gas bill");
    expect(html).toContain("Odie tidied up");
    expect(html).toContain(">Undo</button>");
    expect(html).toContain(">Got it</button>");
  });
  it("shows nothing when there is no digest", () => {
    expect(renderToStaticMarkup(<DigestCard initial={null} />)).toBe("");
  });
  it("says while you were away in code's words", () => {
    const away: Digest = { ...evening, kind: "away", title: "While you were away", text: "1 new for you: Gas bill.", quiet: [], held: [], changes: [] };
    const html = renderToStaticMarkup(<DigestCard initial={away} />);
    expect(html).toContain("While you were away");
    expect(html).not.toContain("Odie tidied up");
  });
});

describe("the Quiet list on Pulse", () => {
  it("lists his rules with delete and the learned kinds with Undo", () => {
    const html = renderToStaticMarkup(<QuietList initial={{
      rules: [{ id: 1, text: 'Fewer "newsletter" cards from news@acme.example: they go in the evening digest', kind: "newsletter", sender: "news@acme.example", at: "" }],
      learned: [{ id: 2, kind: "promo", acted: 0, of: 6, at: "" }] }} />);
    expect(html).toContain("Fewer &quot;newsletter&quot; cards from news@acme.example");
    expect(html).toContain('aria-label="Delete: Fewer');
    expect(html).toContain("promo: in the evening digest (you acted on 0 of 6)");
    expect(html).toContain(">Undo</button>");
  });
  it("shows nothing with no rule and nothing learned", () => {
    expect(renderToStaticMarkup(<QuietList initial={{ rules: [], learned: [] }} />)).toBe("");
  });
});
