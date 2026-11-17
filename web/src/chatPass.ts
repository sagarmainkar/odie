// "Don't ask again in this chat": in Smart, a shell card's second button lets that kind of command (the reason on the
// card) run without asking in that chat only, for 30 minutes. The server decides which cards offer it (detail.chat_pass)
// and gives the pass; these pure functions only choose the words.
import type { Approval } from "./components/ApprovalCard";

export const CHAT_PASS_BUTTON = "Run it, and don't ask again in this chat for 30 min";

// The kinds a pass may cover (the server's own reasons), in words for the owner.
const KIND_WORDS: Record<string, string> = {
  "deletes or stops something": "deleting or stopping things",
  "runs text as commands": "running text as commands",
  "writes a file from code": "writing files from code",
  "sets something to run later or at login": "setting things to run later or at login",
  "installs software (runs its install scripts)": "installing software",
  "edits files in place": "editing files in place",
  "writes a file outside /tmp": "writing files outside ordinary folders",
  "replaces a file": "replacing files",
};

/** A kind a pass may cover, in plain words; null for any other kind (those never get the button).
 *    "deletes or stops something" -> "deleting or stopping things"
 *    "reads secrets"              -> null
 *    undefined                    -> null */
export function kindWords(kind: unknown): string | null {
  if (typeof kind !== "string") return null;
  return KIND_WORDS[kind] ?? null;
}

/** The line under the second button, or null when the card doesn't offer it. Offered only in Smart, on a shell card
 * the server marked (detail.chat_pass), for a kind it can name, and never right after Odie read mail (like the
 * 30-minute pass in Careful).
 *    Smart, run_shell, deletes, marked -> "Only for deleting or stopping things, only in this chat. Everything else still asks."
 *    Careful, or not marked, or a mail card, or risk "from_email" -> null */
export function chatPassScope(a: Approval, smart: boolean): string | null {
  if (!smart || a.tool !== "run_shell") return null;
  if (a.risk === "from_email" || a.risk === "unknown") return null;
  if (a.detail?.chat_pass !== true) return null;
  const words = kindWords(a.detail?.asks_because);
  if (!words) return null;
  return `Only for ${words}, only in this chat. Everything else still asks.`;
}

/** What an answered card says about the pass it gave, with the time it ends in this device's own clock.
 *    ("deletes or stops something", "12:31") -> "Until 12:31, this chat won't ask again for deleting or stopping things."
 *    a kind with no words                    -> "... for this kind of command." */
export function chatPassNote(kind: string, until: string): string {
  const words = kindWords(kind) ?? "this kind of command";
  return `Until ${until}, this chat won't ask again for ${words}.`;
}
