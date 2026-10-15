// Draws a ```mermaid fence (a flowchart, sequence diagram, mind map, Gantt chart…) as SVG. Mermaid is large, so this file
// is fetched only the first time a diagram is drawn (lazy.ts imports it with import()).
//
// The diagram's text is written by a model, so Mermaid runs at its strictest: "strict" escapes HTML in labels and turns
// off click handlers, labels are SVG text (no HTML inside the SVG), and the finished SVG goes through DOMPurify's SVG
// profile before it reaches the page.
import DOMPurify from "dompurify";
import mermaid from "mermaid";

const FONT = '"Plus Jakarta Sans Variable", "Plus Jakarta Sans", system-ui, sans-serif';  // the app's body font
// Mermaid's "base" theme works out the rest of its colours from these few: the app's indigo on its day and night inks.
// git0 / gitBranchLabel0 colour a mind map's centre; cScale0-11 its branches (Mermaid's own night ones come out black).
const SHARED = { fontFamily: FONT, primaryBorderColor: "#7D8CFF", git0: "#7D8CFF", gitBranchLabel0: "#FFFFFF" };
const DAY = { ...SHARED, darkMode: false, background: "#FFFFFF", primaryColor: "#EEF0FF", primaryTextColor: "#1C1B22", lineColor: "#85828F", edgeLabelBackground: "#FFFFFF" };
const NIGHT_BRANCHES = Object.fromEntries([235, 280, 190, 35, 330, 140, 260, 15, 205, 300, 95, 170].map((hue, i) => [`cScale${i}`, `hsl(${hue}, 40%, 32%)`]));
const NIGHT = { ...SHARED, darkMode: true, background: "#110F18", primaryColor: "#2E2F5E", primaryTextColor: "#F3F1F8", lineColor: "#9A96AA", edgeLabelBackground: "#26233A", ...NIGHT_BRANCHES };
let drawn = 0;  // each drawing needs its own element id

/**
 * The diagram as safe SVG markup, in the day or the night colours. Throws when the text isn't a diagram Mermaid can read.
 *   ("flowchart TD\n  A[Apply] --> B[Approve]", false) → '<svg …>…</svg>'
 *   ("flowchart TD\n  A[Apply --> ", false)             → throws "Parse error on line 2: …"
 */
export async function drawDiagram(code: string, night: boolean): Promise<string> {
  mermaid.initialize({
    startOnLoad: false,
    securityLevel: "strict",
    htmlLabels: false,
    flowchart: { htmlLabels: false },
    gantt: { useWidth: 480, axisFormat: "%e %b" },  // drawn for a phone: "3 Oct" ticks, not "2026-10-03"
    theme: "base",
    themeVariables: night ? NIGHT : DAY,
    fontFamily: FONT,
    suppressErrorRendering: true,  // a mistake throws to us; Mermaid draws no error picture of its own
  });
  drawn += 1;
  const { svg } = await mermaid.render(`odie-diagram-${drawn}`, code);
  return DOMPurify.sanitize(svg, { USE_PROFILES: { svg: true, svgFilters: true } });
}
