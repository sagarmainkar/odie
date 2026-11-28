// Libra's voice markup (odie/voice_libra.py): when Libra reads replies aloud, the model may open a reply with a tone
// marker (<tone:wry>) and put a few sound tags where they happen (<laugh>). They are for the voice only: the chat
// never draws them, and copying a reply never carries them. Only these known markers count, so any other
// <something> in a reply stays as it is.

export const TONES = ["warm", "cheerful", "excited", "sad", "frightened", "calm", "serious", "wry", "tender",
  "whispering", "dramatic", "documentary"];
export const TAGS = ["laugh", "chuckle", "giggle", "snicker", "sigh", "gasp", "breath", "heavy breath", "exhales",
  "phew", "short pause", "long pause", "cough", "throat-clearing", "sneeze", "yawn", "sob", "cry", "whimper", "groan",
  "tsk", "shout"];

const escape = (word: string) => word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const MARKER = new RegExp(`[ \\t]*(?:<tone:(?:${TONES.join("|")})>|<(?:${TAGS.map(escape).join("|")})>)`, "gi");
const WHOLE = [...TONES.map((tone) => `<tone:${tone}>`), ...TAGS.map((tag) => `<${tag}>`)];

/**
 * Whether the end of a reply that is still streaming may be the first part of a marker on its way, so it is not
 * drawn yet.  "<to" → true;  "<tone:w" → true;  "<lau" → true;  "<div" → false;  "< 5" → false.
 */
export function couldBeMarker(start: string): boolean {
  const lowered = start.toLowerCase();
  return WHOLE.some((marker) => marker.startsWith(lowered));
}

/**
 * A reply as people see it: tone markers and sound tags taken out with the spaces just before them, and an unfinished
 * marker at the very end (still streaming) held back. Nothing else changes, so code and tables keep their spacing.
 *   "<tone:wry>You paid twice? <laugh> No harm." → "You paid twice? No harm."
 *   "Oh <laugh>, fine."                          → "Oh, fine."
 *   "Hello <tone:w"                              → "Hello "
 *   "a <b>bold</b> move"                         → unchanged
 */
export function hideVoiceMarkup(text: string): string {
  let shown = text;
  const cut = shown.lastIndexOf("<");
  if (cut !== -1 && !shown.slice(cut).includes(">") && couldBeMarker(shown.slice(cut))) {
    shown = shown.slice(0, cut);
  }
  return shown.replace(MARKER, "");
}
