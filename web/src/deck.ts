/** A designed deck in the chat (odie/decks): its PDF (or, without a browser, its PowerPoint) carries the deck: how many
 * slides, the theme, the PowerPoint, and two pictures of each slide (a preview for the strip, a view for the viewer). */
import type { Media } from "./media";

export type DeckPage = { thumb: string; view: string };
export type Deck = { slides: number; theme: string; pages: DeckPage[]; note?: string; pptx?: { id: string; filename: string; size: number } };

const THEME: Record<string, string> = { editorial: "Editorial", minimal: "Minimal", warm: "Warm", bold: "Bold" };

export function deckLine(m: Media): string {
  const d = m.deck;
  if (!d) return "";
  return `${d.slides} slide${d.slides === 1 ? "" : "s"} · ${THEME[d.theme] ?? d.theme}`;
}

/** The previews the strip shows (up to `max`), and how many more there are. */
export function visible(pages: DeckPage[], max = 10): { shown: DeckPage[]; more: number } {
  return { shown: pages.slice(0, max), more: Math.max(0, pages.length - max) };
}

/** The slide `by` away from `at`, kept within the deck. */
export function step(at: number, by: number, n: number): number {
  return Math.max(0, Math.min(n - 1, at + by));
}

/** A finger's move as a step: a sideways swipe of more than 50 px goes to the next (left) or previous (right) slide. */
export function swipe(dx: number, dy: number): -1 | 0 | 1 {
  if (Math.abs(dx) <= 50 || Math.abs(dx) <= Math.abs(dy)) return 0;
  return dx < 0 ? 1 : -1;
}

/** A pinch from `d0` to `d1` px apart, starting at `base`: the new scale, between 1x and 4x. */
export function pinchScale(base: number, d0: number, d1: number): number {
  if (d0 <= 0) return base;
  return Math.max(1, Math.min(4, base * (d1 / d0)));
}

/** A zoomed slide's offset, kept so its edges never pull in from the screen's (none at 1x). */
export function clampPan(x: number, y: number, scale: number, w: number, h: number): { x: number; y: number } {
  const mx = ((scale - 1) * w) / 2, my = ((scale - 1) * h) / 2;
  return { x: Math.max(-mx, Math.min(mx, x)) || 0, y: Math.max(-my, Math.min(my, y)) || 0 };
}
