// Atoms: the smallest blocks. They can stand on their own or sit in a row, section or grid, so a reply can add a badge,
// a button or one number where no ready-made block has one.
import { clean, firstText, https, num, str, type Trail } from "./fields";
import { readKpi, type KpiItem } from "./kpis";

export type BadgeTone = "good" | "warn";
export type HeadingBlock = { type: "heading"; text: string };
export type TextBlock = { type: "text"; text: string };
export type BadgeBlock = { type: "badge"; text: string; tone?: BadgeTone };
export type ButtonBlock = { type: "button"; label: string; run?: string; url?: string };
export type LinkBlock = { type: "link"; text: string; url: string };
export type ImageBlock = { type: "image"; url: string; caption?: string };
export type StatBlock = { type: "stat" } & KpiItem;
export type BarBlock = { type: "bar"; label: string; value: number; max: number; unit?: string };
export type DividerBlock = { type: "divider" };

/**
 * heading: a short title line between blocks. Text (also `title`), up to 80 characters.
 *   {type: "heading", title: "Day 1"} → {type: "heading", text: "Day 1"}
 * Dropped: no text.
 */
export function readHeading(raw: any, here: Trail): HeadingBlock | null {
  const text = firstText([raw.text, raw.title], 80);
  if (!text) return here.drop("heading needs text");
  return { type: "heading", text };
}

/**
 * text: a short paragraph; may use :badge[…], :icon[…], **bold** and [links](https://…). Text (also `content`, `body`).
 *   {type: "text", content: "Best before 9am :icon[sun]"} → {type: "text", text: "Best before 9am :icon[sun]"}
 * Dropped: no text.
 */
export function readText(raw: any, here: Trail): TextBlock | null {
  const text = firstText([raw.text, raw.content, raw.body], 600);
  if (!text) return here.drop("text needs text");
  return { type: "text", text };
}

/** Badge tone words → good, warn, or no tone (a plain grey pill). "success" → "good"; "blue" → undefined. */
export function badgeTone(v: unknown): BadgeTone | undefined {
  const word = typeof v === "string" ? v.toLowerCase() : "";
  if (["good", "success", "positive", "ok"].includes(word)) return "good";
  if (["warn", "warning", "bad", "negative", "danger"].includes(word)) return "warn";
  return undefined;
}

/**
 * badge: a small pill. Text (also `label`), tone good | warn (aliases in badgeTone; anything else is a plain pill).
 *   {type: "badge", label: "Sold out", tone: "warning"} → {type: "badge", text: "Sold out", tone: "warn"}
 * Dropped: no text.
 */
export function readBadge(raw: any, here: Trail): BadgeBlock | null {
  const text = firstText([raw.text, raw.label], 30);
  if (!text) return here.drop("badge needs text");
  return clean({ type: "badge" as const, text, tone: badgeTone(raw.tone) });
}

/**
 * button: one button. Label (also `text`); run sends a message (also `ask`, `message`), url opens an https page.
 *   {type: "button", text: "Book", url: "https://example.com/book"} → {type: "button", label: "Book", url: "https://example.com/book"}
 * Dropped: no label, or neither run nor an https url.
 */
export function readButton(raw: any, here: Trail): ButtonBlock | null {
  const label = firstText([raw.label, raw.text], 40);
  if (!label) return here.drop("button needs a label");
  const run = firstText([raw.run, raw.ask, raw.message], 300);
  const url = https(raw.url);
  if (!run && !url) return here.drop("button needs run or an https url");
  return clean({ type: "button" as const, label, run, url });
}

/**
 * link: a line of linked text. url must be https; text (also `label`, `title`) defaults to the site's name.
 *   {type: "link", url: "https://www.irctc.co.in/nget/train-search"} → {type: "link", text: "irctc.co.in", url: "https://www.irctc.co.in/nget/train-search"}
 * Dropped: no https url.
 */
export function readLink(raw: any, here: Trail): LinkBlock | null {
  const url = https(raw.url ?? raw.href);
  if (!url) return here.drop("link needs an https url");
  const text = firstText([raw.text, raw.label, raw.title], 80) ?? siteName(url);
  return { type: "link", text, url };
}

/** "https://www.irctc.co.in/x" → "irctc.co.in" */
function siteName(url: string): string {
  return new URL(url).hostname.replace(/^www\./, "");
}

/**
 * image: one photo with an optional caption. url (also `src`, `image`) must be https; caption also `alt`, `title`.
 *   {type: "image", src: "https://x.example/a.jpg", alt: "Ooty lake"} → {type: "image", url: "https://x.example/a.jpg", caption: "Ooty lake"}
 * Dropped: no https url.
 */
export function readImage(raw: any, here: Trail): ImageBlock | null {
  const url = https(raw.url) ?? https(raw.src) ?? https(raw.image);
  if (!url) return here.drop("image needs an https url");
  return clean({ type: "image" as const, url, caption: firstText([raw.caption, raw.alt, raw.title], 80) });
}

/**
 * stat: one big number with its label and an optional change chip (a kpis card on its own). Label also `title`.
 *   {type: "stat", title: "Saved", value: 42000, unit: "₹", change: 12} → {type: "stat", label: "Saved", value: 42000, unit: "₹", change: 12, change_unit: "%"}
 * Dropped: no label.
 */
export function readStat(raw: any, here: Trail): StatBlock | null {
  const label = firstText([raw.label, raw.title], 40);
  if (!label) return here.drop("stat needs a label");
  return { type: "stat", ...readKpi({ ...raw, label }) };
}

/**
 * bar: one progress bar, value out of max (also `goal`, `total`; default 100). Label also `title`.
 *   {type: "bar", title: "Packed", value: 6, goal: 9} → {type: "bar", label: "Packed", value: 6, max: 9}
 * Dropped: no label or no numeric value.
 */
export function readBar(raw: any, here: Trail): BarBlock | null {
  const label = firstText([raw.label, raw.title], 40);
  if (!label) return here.drop("bar needs a label");
  const value = num(raw.value);
  if (value === null) return here.drop("bar needs a numeric value");
  let max = num(raw.max) ?? num(raw.goal) ?? num(raw.total) ?? 100;
  if (max <= 0) max = 100;
  return clean({ type: "bar" as const, label, value, max, unit: str(raw.unit, 12) });
}

/** divider: a thin line between blocks. Takes no fields. {type: "divider"} → {type: "divider"} */
export function readDivider(): DividerBlock {
  return { type: "divider" };
}
