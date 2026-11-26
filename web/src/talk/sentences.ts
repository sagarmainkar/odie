// What Talk says of a reply, sentence by sentence as it streams in (the Mac app's SentenceStream, kept small): only the
// prose. Code, visual blocks and tables are drawn in the chat, never read out. Libra's sound tags stay in the words
// (<laugh> is performed); the tone marker goes, and travels beside each sentence instead (toneOf).
import { TONES } from "../blocks/voiceMarkup";

const TONE_MARKER = new RegExp(`<tone:(${TONES.join("|")})>`, "i");
const TONE_MARKERS = new RegExp(`[ \\t]*<tone:(?:${TONES.join("|")})>`, "gi");

/** The tone a reply asks for: "<tone:wry>You paid twice?" → "wry"; "Plain." → null; "<tone:grumpy>Hi" → null. */
export function toneOf(text: string): string | null {
  const found = TONE_MARKER.exec(text);
  if (!found) return null;
  return found[1].toLowerCase();
}

/**
 * A reply's prose as it would be said: fenced code and blocks dropped (an unfinished fence at the end too, since it is
 * still streaming), table rows dropped, the tone marker taken out, Markdown marks taken off.
 *   "<tone:calm>**Paid.** See:\n```odie-blocks\n[…]\n```\nDone." → "Paid. See:\n\nDone."
 */
export function speechOf(markdown: string): string {
  let text = markdown.replace(/```[\s\S]*?```/g, "\n");
  const open = text.indexOf("```");
  if (open !== -1) text = text.slice(0, open);
  text = text.split("\n").filter((line) => !line.trim().startsWith("|")).join("\n");
  text = text.replace(TONE_MARKERS, "");
  text = text.replace(/\[([^\]]+)\]\([^)]+\)/g, "$1");
  text = text.replace(/^[ \t]*(?:#+|[-*•]|\d+\.)[ \t]+/gm, "");
  return text.replace(/[*_`#]+/g, "");
}

/** The sentences in some prose, each with whether it is over (an end mark or a blank line after it). The last one
 *  may still be growing.  "Paid. The bank sent" → [["Paid.", true], ["The bank sent", false]] */
export function sentencesIn(prose: string): { text: string; finished: boolean }[] {
  const found: { text: string; finished: boolean }[] = [];
  // a run of anything but an end mark or a newline, where an end mark inside a word or number ("4,240.50") doesn't
  // count; then the sentence's end: marks before a space or the end, or a newline
  const pattern = /(?:[^.!?\n]|[.!?]+(?![\s]|$))+(?:[.!?]+(?=\s|$)|\n\s*\n|\n)?/g;
  for (const match of prose.matchAll(pattern)) {
    const piece = match[0];
    const text = piece.trim();
    if (!text) continue;
    const finished = /[.!?]$/.test(text) || /\n/.test(piece);
    found.push({ text, finished });
  }
  return mergeLoneSounds(found);
}

/** A piece that is only a sound tag ("<laugh>" after the last sentence) goes with the sentence before it, so it is
 *  never a request of its own.  ["Done.", "<chuckle>"] → ["Done. <chuckle>"] */
function mergeLoneSounds(pieces: { text: string; finished: boolean }[]): { text: string; finished: boolean }[] {
  const out: { text: string; finished: boolean }[] = [];
  for (const piece of pieces) {
    const onlySound = /^(?:<[a-z :-]+>\s*)+$/i.test(piece.text);
    if (onlySound && out.length > 0) {
      out[out.length - 1] = { text: `${out[out.length - 1].text} ${piece.text}`, finished: piece.finished };
      continue;
    }
    out.push(piece);
  }
  return out;
}

/**
 * The sentences of one streaming reply: `feed` is given the whole reply so far and returns the sentences newly over,
 * once each; `finish` returns whatever the end leaves. Counts are compared, never words, so a rewritten reply never
 * repeats a sentence.
 *   feed("Paid. The bank") → ["Paid."];  feed("Paid. The bank sent it.") → ["The bank sent it."];  finish(…) → []
 */
export class TalkSentences {
  private said = 0;

  feed(reply: string): string[] {
    const prose = speechOf(reply);
    const pieces = sentencesIn(prose);
    let ready = pieces.filter((piece) => piece.finished).length;
    // mid-stream, an end mark at the very end may be a decimal point still arriving ("₹4,240." then "50"): the last
    // sentence counts as over only once something follows it
    if (ready === pieces.length && ready > 0 && !/\s$/.test(prose)) ready -= 1;
    return this.take(pieces.slice(0, ready).map((piece) => piece.text));
  }

  finish(reply: string): string[] {
    const pieces = sentencesIn(speechOf(reply));
    return this.take(pieces.map((piece) => piece.text));
  }

  private take(sentences: string[]): string[] {
    const fresh = sentences.slice(this.said);
    this.said = Math.max(this.said, sentences.length);
    return fresh;
  }
}
