import { useContext, useEffect, useState } from "react";
import type { CSSProperties } from "react";
import { ReplyPlace } from "../blocks/SavedPlace";
import { loadDiagrams } from "../lazy";
import { ChartPending } from "./ChartBlock";

type Drawing = { code: string; svg: string; width: number } | { code: string; error: string };

/** True while the look is the night one (theme.ts sets data-tod on <html>); follows it when it changes. */
function useNight(): boolean {
  const [night, setNight] = useState(() => document.documentElement.dataset.tod === "night");
  useEffect(() => {
    const html = document.documentElement;
    const watch = new MutationObserver(() => setNight(html.dataset.tod === "night"));
    watch.observe(html, { attributes: true, attributeFilter: ["data-tod"] });
    return () => watch.disconnect();
  }, []);
  return night;
}

/**
 * How wide Mermaid drew the diagram, from its viewBox, in CSS pixels; 0 when it doesn't say.
 *   '<svg viewBox="0 0 642.5 380" …>' → 642.5
 *   '<svg width="100%">'              → 0
 */
function drawnWidth(svg: string): number {
  const box = svg.match(/viewBox="[-\d.]+ [-\d.]+ ([\d.]+) [\d.]+"/);
  if (!box) return 0;
  return Number(box[1]);
}

/** The first line of Mermaid's complaint, short enough for a note: "Parse error on line 2:\n…" → "Parse error on line 2:". */
function firstLine(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  return message.split("\n")[0].slice(0, 120);
}

/**
 * A ```mermaid fence drawn as a diagram. Mermaid is fetched the first time a diagram is drawn. While the reply is still
 * streaming in, a placeholder shows (half a diagram is usually a broken one). If the text has a mistake, the text
 * shows as written with a short note, never an empty box. Colours follow the day and night looks.
 */
export function Diagram({ code }: { code: string }) {
  const streaming = useContext(ReplyPlace)?.streaming ?? false;
  const night = useNight();
  const [drawing, setDrawing] = useState<Drawing | null>(null);
  useEffect(() => {
    if (streaming) return;
    let stillShown = true;
    loadDiagrams()
      .then((diagrams) => diagrams.drawDiagram(code, night))
      .then((svg) => { if (stillShown) setDrawing({ code, svg, width: drawnWidth(svg) }); })
      .catch((error: unknown) => { if (stillShown) setDrawing({ code, error: firstLine(error) }); });
    return () => { stillShown = false; };
  }, [code, night, streaming]);

  const ready = !streaming && drawing?.code === code;  // a drawing of older text (a redraw is coming) never shows
  if (!ready || !drawing) return <ChartPending />;
  if ("error" in drawing) {
    return (
      <div className="diagram-broken">
        <div className="diagram-note">Couldn’t draw this diagram: {drawing.error}</div>
        <pre><code>{code}</code></pre>
      </div>
    );
  }
  // --drawn-w: the diagram's own width. It shrinks to fit a phone, but not below 60% (its words stay readable);
  // wider than that, it scrolls sideways inside its box.
  const size = { "--drawn-w": `${drawing.width || 600}px` } as CSSProperties;
  // Safe as HTML: diagram.ts drew it with Mermaid's strict mode and passed it through DOMPurify.
  return <div className="diagram" style={size} dangerouslySetInnerHTML={{ __html: drawing.svg }} />;
}
