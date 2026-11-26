// The text of a reply as the chat draws it. Small models' stray fences (```odie-checklist), block tags (<callout>) and
// one-line fences become real ```odie-blocks fences only here, so anything that counts a reply's fences (the number a
// checklist's ticks are saved under, whether a line holds blocks) reads this text, never the raw one.
import { plainMath } from "../plainMath";
import { liftOneLineFences } from "./oneLineFence";
import { tidyStrayBlocks } from "./strayBlocks";
import { hideVoiceMarkup } from "./voiceMarkup";

/**
 * A reply's text as the chat draws it: Libra's voice markup hidden, one-line fences lifted, stray blocks tidied,
 * LaTeX symbols made plain.
 *   "<tone:wry>You paid twice? <laugh> No harm."       → "You paid twice? No harm."
 *   'List ```odie-blocks: [{"type": "checklist"}] ```' → 'List\n```odie-blocks\n[{"type": "checklist"}]\n```'
 *   '```odie-checklist\n{"items": ["Jacket"]}\n```'    → '```odie-blocks\n{"items":["Jacket"],"type":"checklist"}\n```'
 */
export function drawnText(text: string): string {
  const heard = hideVoiceMarkup(text);
  return plainMath(tidyStrayBlocks(liftOneLineFences(heard)));
}
