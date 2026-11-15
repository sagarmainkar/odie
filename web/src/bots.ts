/** Bots (odie/workers/bots.py): named background helpers. The chief makes most of them; Settings → Bots changes any
 * bot's role, prompt, powers and model. Questions a bot waits on (a tap, a sign-in) are answered on Today. */

export type BotModel = { provider: string; model: string } | null;
export type Bot = { name: string; role: string; prompt: string; model: BotModel; powers: string[]; made_by: string; edited_by_user: boolean; chief: boolean };
export type JobAsk = { id: string; job_id: string; kind: "tap" | "sign_in"; text: string; why: string | null; site: string | null;
  card: { tab?: string; url?: string; site?: string } | null; created_at: string };
export type ModelChoice = { value: string; label: string };

export const POWER_WORDS: Record<string, string> = {
  web: "Web search and pages",
  files: "Files in its folder",
  shell: "Run commands (risky ones refused)",
  browser: "Your signed-in browser (risky steps wait for your tap)",
};

/** The model a bot runs on, in words: none picked -> "Chat model"; ollama/lfm3:latest -> "lfm3:latest · ollama". */
export function modelWords(m: BotModel): string {
  return m ? `${m.model} · ${m.provider}` : "Chat model";
}

/** The model picker's value for a bot's pick: none -> ""; ollama/lfm3:latest -> "ollama|lfm3:latest". */
export function modelValue(m: BotModel): string {
  return m ? `${m.provider}|${m.model}` : "";
}

/** A picker value back to a pick: "" -> null (the chat's model); "ollama|lfm3:latest" -> ollama/lfm3:latest;
 * "openrouter|a|b" -> openrouter / "a|b" (only the first bar splits). */
export function modelFrom(value: string): BotModel {
  const bar = value.indexOf("|");
  if (!value || bar < 0) return null;
  return { provider: value.slice(0, bar), model: value.slice(bar + 1) };
}

/** The picker's choices: the chat's model first, then every listed model of every reachable provider, and the bot's
 * current pick even when its provider no longer lists it (so opening the editor never changes it by itself). */
export function modelChoices(providers: { id: string; name: string; models: { id: string }[]; error: string | null }[], current: BotModel): ModelChoice[] {
  const out: ModelChoice[] = [{ value: "", label: "Chat model" }];
  for (const p of providers) {
    if (p.error) continue;
    for (const m of p.models) out.push({ value: `${p.id}|${m.id}`, label: `${m.id} · ${p.name}` });
  }
  const now = modelValue(current);
  if (now && !out.some((c) => c.value === now)) out.push({ value: now, label: `${modelWords(current)} (not listed now)` });
  return out;
}

/** Who made a bot, in a few words: the chief's own -> "made by the chief"; changed in Settings -> "yours";
 * Odie's (the chief itself) -> "always here"; one of Odie's starter team -> "starter". */
export function madeWords(b: Bot): string {
  if (b.chief) return "always here";
  if (b.edited_by_user) return "yours";
  if (b.made_by === "odie") return "starter";
  return "made by the chief";
}
