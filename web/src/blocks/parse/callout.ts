import { clean, firstText, type Trail } from "./fields";

export type Tone = "info" | "tip" | "warn";
export type CalloutBlock = { type: "callout"; tone: Tone; title?: string; text: string };

// The tone names models reach for, mapped to the three we draw. Anything not listed is "info".
const TONES: Record<string, Tone> = {
  info: "info", note: "info", neutral: "info",
  tip: "tip", success: "tip", good: "tip", idea: "tip",
  warn: "warn", warning: "warn", caution: "warn", danger: "warn", alert: "warn", error: "warn",
};

/**
 * callout: a tinted box with an icon, for a warning, a tip or the one-line takeaway.
 * Accepts tone (also `variant`): info | tip | warn, plus the aliases in TONES; a title (optional) and text (also `body`,
 * `message`, `content`). With only a title, the title becomes the text.
 *   {type: "callout", variant: "warning", body: "Carry cash: card machines are rare."}
 *   → {type: "callout", tone: "warn", text: "Carry cash: card machines are rare."}
 * Dropped: neither text nor title.
 */
export function readCallout(raw: any, here: Trail): CalloutBlock | null {
  const toneWord = firstText([raw.tone, raw.variant], 20)?.toLowerCase() ?? "info";
  const tone = TONES[toneWord] ?? "info";
  let title = firstText([raw.title], 80);
  let text = firstText([raw.text, raw.body, raw.message, raw.content], 400);
  if (!text && title) {
    text = title;
    title = undefined;
  }
  if (!text) return here.drop("callout needs text");
  return clean({ type: "callout" as const, tone, title, text });
}
