/** The report reader (components/ReportReader.tsx): a made file Odie can open and show as text inside the app, so a
 * research report can be read on a phone, where a .md download goes nowhere. */

/** How the reader shows a file: Markdown formatted (headings, lists, tables, links), or plain text as written. */
export type ReaderFormat = "markdown" | "plain";

const FORMAT_BY_EXT: Record<string, ReaderFormat> = { md: "markdown", markdown: "markdown", txt: "plain" };

function extensionOf(filename: string): string {
  if (!filename.includes(".")) return "";
  return filename.split(".").pop()!.toLowerCase();
}

/**
 * Decides how the reader shows a file, by its name: Markdown is formatted, plain text is shown as written, anything
 * else isn't for the reader (it stays a download). "AI chips.md" -> "markdown"; "notes.TXT" -> "plain";
 * "deck.pptx" -> null; "README" (no extension) -> null.
 */
export function readerFormat(filename: string): ReaderFormat | null {
  const ext = extensionOf(filename);
  return FORMAT_BY_EXT[ext] ?? null;
}

/**
 * Decides whether a file card opens the reader on a tap (instead of downloading). Only text the reader can show:
 * "AI chips.md" -> true (opens the reader); "list.txt" -> true; "budget.csv" -> false (a download);
 * "report.pdf" -> false.
 */
export function opensInReader(filename: string): boolean {
  return readerFormat(filename) !== null;
}

/** What the reader says when the file couldn't be fetched: 404 -> it's gone; anything else -> try again.
 *  404 -> "This file isn't on Odie any more."; 500 -> "Couldn't open the file (HTTP 500). Try again." */
export function readerError(status: number): string {
  if (status === 404) return "This file isn't on Odie any more.";
  return `Couldn't open the file (HTTP ${status}). Try again.`;
}
