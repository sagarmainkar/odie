// How the chat shows one fenced code block of a reply. The chat's Markdown (Chat.tsx) draws from this, and the chat
// replay's scorer (eval/chatScore.ts) reads it, so "what the owner saw" and "what the score says" can't drift apart.
import { parseChart, type ChartSpec } from "../components/ChartBlock";
import { parseImages, type ImagesSpec } from "../components/ImageStrip";
import { cleanSvg, svgComplete } from "../svgBlock";
import { parseBlocks, type Block } from "./parse";

export type FenceShown =
  | { as: "blocks"; blocks: Block[] }   // drawn as blocks (none drawable: "Couldn't draw this", readable as text)
  | { as: "images"; spec: ImagesSpec }  // a photo strip
  | { as: "chart"; spec: ChartSpec }    // a chart
  | { as: "diagram" }                   // a Mermaid diagram (flowchart, sequence, mind map, Gantt…)
  | { as: "svg"; svg: string }          // a drawing the model wrote as SVG, cleaned (svgBlock.ts)
  | { as: "waiting" }                   // the "drawing…" placeholder: still streaming in (stays so if the reply ended there)
  | { as: "broken" }                    // a blocks fence that isn't JSON: "Couldn't draw this", never shown as code
  | { as: "code" };                     // a plain code box

/**
 * Decides how the chat shows a fence, from its language and text. Worked examples:
 *   ("odie-blocks", '[{"type":"divider"}]')          → blocks
 *   ("odie-blocks", '[{"type":"divider"}')           → waiting (no closing "]": still streaming in)
 *   ("odie-blocks", '[{"type": divider}]')           → broken (ends in "]" but isn't JSON)
 *   ("odie-images", '{"images":[{"url":"https://…"}]}') → images
 *   ("json", '{"type":"bar","x":[…],"series":[…]}')  → chart (a chart written in a json fence is still drawn)
 *   ("mermaid", "flowchart TD\n  A --> B")         → diagram (one with a mistake shows its text and a note)
 *   ("odie-svg", "<svg …>…</svg>")                 → svg (cleaned; without its closing tag yet: waiting; not SVG at all: code)
 *   ("json", '{"a": 1}')                             → code
 *   ("python", "print(1)")                           → code
 */
export function howChatShowsFence(lang: string, code: string): FenceShown {
  const end = code.trim();
  if (lang === "odie-blocks") {
    const blocks = parseBlocks(code);
    if (blocks) return { as: "blocks", blocks };
    if (!end.endsWith("]")) return { as: "waiting" };
    return { as: "broken" };
  }
  if (lang === "odie-images" || lang === "images") {
    const spec = parseImages(code);
    if (spec) return { as: "images", spec };
    if (!end.endsWith("}") && !end.endsWith("]")) return { as: "waiting" };
  }
  if (lang === "json" && code.includes('"images"')) {
    const spec = parseImages(code);
    if (spec) return { as: "images", spec };
  }
  if (lang === "odie-chart" || lang === "json" || lang === "chart") {
    const spec = parseChart(code);
    if (spec) return { as: "chart", spec };
    if (lang !== "json" && !end.endsWith("}")) return { as: "waiting" };
  }
  if (lang === "mermaid") return { as: "diagram" };
  if (lang === "odie-svg" || lang === "svg") {
    if (!svgComplete(code)) return /^\s*(<\?xml|<!--|<svg)/i.test(code) || !end ? { as: "waiting" } : { as: "code" };
    const svg = cleanSvg(code);
    if (svg) return { as: "svg", svg };
  }
  return { as: "code" };
}
