// A list row with no icon and no photo shows the first letter of its title in a coloured circle, the way a mail app
// shows senders. The colour comes from the name, so the same sender gets the same colour in every list.
import { splitInline } from "./inlineSyntax";

/** What a row shows at its left, after the rank number (if any). */
export type RowLead = "image" | "icon" | "initial" | "none";

/** The chart palette's colours that white text reads well on (4, an amber, is too light). */
const AVATAR_COLOURS = [1, 2, 3, 5, 6, 7, 8];

/**
 * Which picture a row leads with. A photo when it has one and may show it (a private chat holds web photos back);
 * else its icon; else the first letter of its title, unless the list is ranked (the rank number already fills that
 * spot) or the title has no letter to show. Worked examples:
 *   {title: "Asha · Lease renewal", icon: "alert"}            -> "icon"
 *   {title: "Asha · Lease renewal"}                            -> "initial" (an "A" in a circle)
 *   {title: "Asha", image: "https://…"} in a private chat      -> "initial" (the photo is held back)
 *   {title: "Third Wave"} in a ranked list                     -> "none" (the rank number is there)
 *   {title: "🎉🎉"}                                              -> "none" (no letter to show)
 */
export function rowLead(item: { title: string; icon?: string; image?: string }, ranked: boolean, photosHeld: boolean): RowLead {
  if (item.image && !photosHeld) return "image";
  if (item.icon) return "icon";
  if (ranked) return "none";
  if (initialOf(item.title) === null) return "none";
  return "initial";
}

/**
 * The letter for a title's circle: the first letter or digit of the words a reader sees, upper-cased. Badges, icons,
 * emoji and punctuation are skipped; null when nothing is left.
 *   "Asha · Lease renewal"      -> "A"
 *   "📦 amazon.in · Your order"  -> "A"
 *   ":badge[New] **ravi**"      -> "R" (the badge's word isn't the name)
 *   "🎉" or "  "                -> null
 */
export function initialOf(title: string): string | null {
  const words = readableWords(title);
  const first = words.match(/[\p{L}\p{N}]/u);
  if (!first) return null;
  return first[0].toLocaleUpperCase();
}

/**
 * The circle's colour, as a CSS value: one of the palette's colours, picked by the name (the title up to " · ",
 * ignoring case and spaces at the ends), so a sender keeps their colour across rows and replies.
 *   "Asha · Lease renewal" and "asha · Dinner on Sat" -> the same colour
 *   "Asha" and "Ravi"                                  -> usually different ones (7 colours to go round)
 */
export function avatarColour(title: string): string {
  const name = nameOf(title);
  let hash = 0;
  for (const ch of name) {
    hash = (hash * 31 + ch.codePointAt(0)!) % 1_000_003;
  }
  const pick = AVATAR_COLOURS[hash % AVATAR_COLOURS.length];
  return `var(--t-chart-${pick})`;
}

/** The part of a title that names someone: before " · " when the row is "Sender · subject", else all of it. */
function nameOf(title: string): string {
  const words = readableWords(title);
  const sender = words.split(" · ")[0];
  return sender.trim().toLowerCase();
}

/** The title's own words: plain text, bold and link labels, without badges or icons. */
function readableWords(title: string): string {
  const words: string[] = [];
  for (const piece of splitInline(title)) {
    if (piece.kind === "text" || piece.kind === "bold" || piece.kind === "link") words.push(piece.text);
  }
  return words.join("");
}
