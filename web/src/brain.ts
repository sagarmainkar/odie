/** The brain check's report, as the Brain screen shows it. */
export type BrainPart = { name: "tools" | "result" | "speed" | "context"; status: "pass" | "warn" | "fail" | "unknown"; detail: string };
export type BrainReport = { provider: string; model: string; verdict: "good" | "slow" | "warn" | "fail"; sentence: string; parts: BrainPart[]; checked_at: string };

const LABEL: Record<BrainPart["name"], string> = { tools: "Tool calls", result: "Using results", speed: "Speed", context: "Context" };
const MARK: Record<BrainPart["status"], string> = { pass: "✓", warn: "!", fail: "✕", unknown: "·" };

export function tone(r: BrainReport): "good" | "warn" | "bad" {
  return r.verdict === "good" ? "good" : r.verdict === "fail" ? "bad" : "warn";
}

export function partLine(p: BrainPart): string {
  return `${MARK[p.status]} ${LABEL[p.name]}: ${p.detail}`;
}

/** The sentence without the model's name in front (the card already shows it; Ollama names have colons in them). */
export function said(r: BrainReport): string {
  const prefix = `${r.model}: `;
  return r.sentence.startsWith(prefix) ? r.sentence.slice(prefix.length) : r.sentence;
}

/** A word or two for the model list. */
export function badge(r: BrainReport): string {
  return r.verdict === "good" ? "✓ good" : r.verdict === "fail" ? "✕ won't work" : `! ${r.verdict}`;
}

export type BrainState = "ready" | "unreachable" | "none";

/** What the Brain card and Settings' Brain row say about the model Odie would use right now.
 *    chosen, reachable                        -> "ready"       (the model's name, "on this computer" or "leaves…")
 *    chosen, its provider doesn't answer      -> "unreachable" (the name, and "LM Studio isn't reachable")
 *    nothing chosen, the default doesn't answer -> "none"      ("No brain yet", never a model nobody picked)
 *    nothing chosen, but the default answers  -> "ready"       (LM Studio already running with that model) */
export function brainState(chosen: boolean | undefined, reachable: boolean | undefined): BrainState {
  if (reachable === false && chosen === false) return "none";
  if (reachable === false) return "unreachable";
  return "ready";
}
