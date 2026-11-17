import { withPickOf } from "./pick";

// Settings has no list of personalities. Its name, picture and personality boxes show and edit whoever is picked in
// the chat's switcher: it is a context switch. These are the small decisions that make it so.

/** Where the name is read and saved: always saying who, even everyday Odie ("" -> "?personality="). */
export function personaUrl(pick: string): string { return withPickOf("/api/persona", pick, true); }

export function avatarUrl(pick: string): string { return withPickOf("/api/persona/avatar", pick, true); }

export function soulUrl(pick: string): string { return withPickOf("/api/soul", pick, true); }

/** Delete is offered for a personality, never for everyday Odie:  "abc" -> true;  "" -> false. */
export function showsDelete(pick: string): boolean { return pick !== ""; }

/** Whether Settings says who is being edited: only once there is someone else to edit, so an install with no
 *  personalities looks as it always has:  ("", 0) -> false;  ("", 2) -> true;  ("abc", 1) -> true. */
export function showsWhoLine(pick: string, howMany: number): boolean { return pick !== "" || howMany > 0; }

export function whoLine(name: string): string { return `Editing ${name}`; }

/** The question before a personality is deleted: what goes with it, and what Odie can't reach. */
export function deleteWords(name: string, threads: number): string {
  let what = `Delete ${name}?`;
  if (threads === 1) what = `Delete ${name} and its 1 thread?`;
  if (threads > 1) what = `Delete ${name} and its ${threads} threads?`;
  return `${what} Its threads, memory, instructions and picture are erased for good, and so are the debug copies of `
    + "recent model requests. Not erased: log lines, and anything already sent to a tracing service.";
}

// ── Settings → Brain: the brain of whoever is picked ──

/** The models list and the picked one's brain: always saying who ("" -> "?personality="). */
export function modelsUrl(pick: string): string { return withPickOf("/api/models", pick, true); }

/** Where the picked one's brain is chosen (PUT) or, for a personality, set back to "Same as Odie" (DELETE). */
export function brainChoiceUrl(pick: string): string { return withPickOf("/api/models/selection", pick, true); }

export const SAME_AS_ODIE = "Same as Odie";

/** A personality thinks with everyday Odie's brain or one of its own; Odie has no one to follow:
 *  "abc" -> true (the first choice);  "" -> false. */
export function showsSameAsOdie(pick: string): boolean { return pick !== ""; }

export function brainHeading(name: string): string { return `${name} is using`; }

export type PickedBrain = { provider: string; model: string; same_as_odie?: boolean; gone?: boolean; reachable?: boolean };

/** The model's own name, without the folder some providers put before it: "lmstudio-community/gemma-4" -> "gemma-4". */
function shortModel(model: string): string { return model.split("/").pop() ?? model; }

/** The Settings row under Brain for a personality's brain:
 *    same as Odie's gemma on LM Studio     -> "Same as Odie · gemma-4 · LM Studio"
 *    its own qwen on the work box          -> "qwen3.8 · Work box"   (" isn't reachable" when it doesn't answer)
 *    its own, the provider removed since   -> "qwen3.8 · isn't set up any more: pick another" */
export function pickedBrainSub(brain: PickedBrain, providerName: string): string {
  const model = shortModel(brain.model);
  if (brain.gone) return `${model} · isn't set up any more: pick another`;
  const where = brain.reachable === false ? `${providerName} isn't reachable` : providerName;
  if (brain.same_as_odie) return `${SAME_AS_ODIE} · ${model} · ${where}`;
  return `${model} · ${where}`;
}

export function goneWords(name: string): string {
  return `${name}'s brain isn't set up any more, so ${name} won't answer. Pick another below, or ${SAME_AS_ODIE}.`;
}

// ── Settings → Connected apps: which ones the picked one may use ──

/** The apps, with whether the picked one may use each (canUse); a new app is saved here too, and is the picked one's. */
export function appsUrl(pick: string): string { return withPickOf("/api/mcp", pick, true); }

export function connectUrl(pick: string): string { return withPickOf("/api/mcp/connect", pick, true); }

export function canUseUrl(name: string, pick: string): string {
  return withPickOf(`/api/mcp/${encodeURIComponent(name)}/access`, pick, true);
}

export function canUseLabel(name: string): string { return `${name} can use this`; }

/** Whether each app shows "<name> can use this": only once there is someone else to switch it for, so an install with
 *  no personalities looks as it always has:  ("", 0) -> false;  ("", 1) -> true;  ("abc", 1) -> true. */
export function showsCanUse(pick: string, howMany: number): boolean { return showsWhoLine(pick, howMany); }
