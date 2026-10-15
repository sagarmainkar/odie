// Libraries too big for the app's first load, fetched the first time something on screen needs them and kept after.

type Highlighter = typeof import("./highlight");

let highlighting: Promise<Highlighter> | null = null;
let highlighter: Highlighter | null = null;

/** The code highlighter (highlight.ts), fetched the first time any code box asks; later boxes get the same one. */
export function loadHighlighter(): Promise<Highlighter> {
  if (!highlighting) {
    highlighting = import("./highlight").then((module) => {
      highlighter = module;
      return module;
    });
  }
  return highlighting;
}

/** The highlighter if it has already arrived, so a code box drawn after the first one is coloured from the start. */
export function highlighterIfLoaded(): Highlighter | null {
  return highlighter;
}

type Diagrams = typeof import("./diagram");

let diagrams: Promise<Diagrams> | null = null;

/** Mermaid (diagram.ts), fetched the first time any diagram is drawn; later diagrams get the same one. */
export function loadDiagrams(): Promise<Diagrams> {
  if (!diagrams) diagrams = import("./diagram");
  return diagrams;
}
