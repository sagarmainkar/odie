import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { ReplyText } from "../screens/Chat";
import { liftOneLineFences } from "./oneLineFence";

vi.mock("../components/ToBody", () => ({ ToBody: () => null }));  // the photo viewer's portal needs a browser page

// Gemma 4 26B's exact lines from the owner's chat (11 Oct 2026): whole odie-images fences on one line.
const COORG = '```odie-images: {"title": "Coorg in October", "images": [{"url": "https://d4b28jbnqso5g.cloudfront.net/wp-content/uploads/2026/10/Coorg-winter.png", "caption": "Lush green rolling hills of Coorg with mist drifting through the valleys.", "source": "weatherapi.com"}]} ```';
const RESORTS = '```odie-images: {"title": "Luxury Resorts in Coorg", "images": [{"url": "https://dynamic-media-cdn.tripadvisor.com/media/photo-o/2f/d0/eb/dd/nestled-in-the-heart.jpg?w=1200&h=-1&s=1", "caption": "A luxurious resort nestled in the heart of lush green hills.", "source": "Tripadvisor"}, {"url": "https://www.theleela.com/prod/content/assets/2026-03/4-%20Architecture_1920x950.jpg?VersionId=lpk5T01Iu7vgn1_LnBskplThWfkF9QjP", "caption": "Scenic views with modern architecture and calm waters.", "source": "The Leela"}]} ```';

const GEMMA_REPLY = `The weather in Coorg looks absolutely stunning for your trip! 🌿

${COORG}

**Weather Forecast Summary:**
*   **Temperatures:** Pleasant daytime highs around **24°C–27°C**.`;

describe("one-line fences", () => {
  it("lifts Gemma's one-line odie-images fence into a real one", () => {
    const lifted = liftOneLineFences(COORG);
    expect(lifted.split("\n")).toEqual([
      "```odie-images",
      COORG.slice("```odie-images: ".length, -" ```".length),
      "```",
    ]);
  });
  it("draws Gemma's reply as photos, not JSON in inline code", () => {
    const html = renderToStaticMarkup(<ReplyText text={GEMMA_REPLY} />);
    expect(html).toContain("Coorg-winter.png");
    expect(html).toContain("<img");
    expect(html).not.toContain("<code>");
    expect(html).not.toContain("&quot;images&quot;");
    expect(html).toContain("Weather Forecast Summary");
  });
  it("draws the two-photo reply too", () => {
    const html = renderToStaticMarkup(<ReplyText text={`I've found some resorts! 🌿✨\n\n${RESORTS}\n\nMy top picks:`} />);
    expect(html).toContain("tripadvisor.com");
    expect(html).toContain("theleela.com");
    expect(html).not.toContain("<code>");
  });
  it("lifts a fence written after text on the same line, and odie-blocks without a colon", () => {
    const text = 'Here you go ```odie-blocks [{"type": "callout", "text": "Hi"}]``` and more';
    expect(liftOneLineFences(text)).toBe('Here you go \n```odie-blocks\n[{"type": "callout", "text": "Hi"}]\n```\n and more');
  });
  it("moves JSON written on a fence's opening line onto the next line", () => {
    const text = '```odie-blocks: [{"type": "callout",\n"text": "Hi"}]\n```';
    expect(liftOneLineFences(text)).toBe('```odie-blocks\n[{"type": "callout",\n"text": "Hi"}]\n```');
  });
  it("leaves real fences, other code and replies without one alone", () => {
    const real = '```odie-images\n{"images": [{"url": "https://x.example/a.jpg"}]}\n```';
    expect(liftOneLineFences(real)).toBe(real);
    const inCode = '```text\n```odie-blocks [{"type": "callout", "text": "Hi"}] ```\n```';
    expect(liftOneLineFences(inCode)).toBe(inCode);
    expect(liftOneLineFences("Plain `code` and text")).toBe("Plain `code` and text");
  });
  it("makes a one-line fence still streaming in an open fence, so the chat shows it as coming", () => {
    const partial = '```odie-images: {"title": "Coorg", "images": [{"url": "https://x.example/a.jpg"';
    expect(liftOneLineFences(partial)).toBe('```odie-images\n{"title": "Coorg", "images": [{"url": "https://x.example/a.jpg"');
  });
});
