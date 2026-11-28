/** One row of Settings → Providers. base_url is where Odie reaches it now; a built-in one (local, preset) also has
 *  default_url, its own address, and address_from_env when Odie's environment fixes the address. */
export type ProviderInfo = {
  id: string; name: string; kind: "local" | "preset" | "custom"; connected: boolean; base_url?: string;
  from_env?: boolean; default_url?: string; address_from_env?: boolean; has_key?: boolean;
};
export type Model = { id: string; local: boolean };
/** What the server said when asked whether a provider answers (POST /api/providers/{id}/check). */
export type AddressCheck = { ok: boolean; models: number | null; problem: string | null };

/** Where to get each preset's key (opens in the browser). */
export const KEY_PAGES: Record<string, string> = {
  openai: "https://platform.openai.com/api-keys",
  openrouter: "https://openrouter.ai/keys",
  gemini: "https://aistudio.google.com/apikey",
  anthropic: "https://console.anthropic.com/settings/keys",
};

export function providerSub(p: ProviderInfo): string {
  if (p.kind === "local" && movedAddress(p)) return `${p.connected ? "Running" : "Not answering"} at ${hostAndPort(p.base_url ?? "")}`;
  if (p.kind === "local") return p.connected ? "Running on this computer" : "Not running on this computer";
  if (p.kind === "custom") return p.base_url ?? "Custom";
  if (!p.connected) return "Add a key to use its models";
  return p.from_env ? "Key set in the environment" : p.id === "openai" ? "Connected · also powers OpenAI voices" : "Connected";
}

/** Models to show for one provider: all that match the filter; with no filter, the first `limit` plus the chosen one. */
export function visibleModels(models: Model[], query: string, limit: number, chosen?: string): { shown: Model[]; hidden: number } {
  const q = query.trim().toLowerCase();
  if (q) {
    const shown = models.filter((m) => m.id.toLowerCase().includes(q));
    return { shown, hidden: 0 };
  }
  if (models.length <= limit) return { shown: models, hidden: 0 };
  const shown = models.slice(0, limit);
  const pick = models.find((m) => m.id === chosen);
  if (pick && !shown.includes(pick)) shown.unshift(pick);
  return { shown, hidden: models.length - shown.length };
}

/** How to change a provider's address, in plain words under its models on the Brain screen. Every provider's address,
 *  built-in or custom, is edited in Settings → Providers.
 *    {base_url: "http://localhost:11434/v1"} -> "change it in Settings → Providers"
 *    {} (no address)                         -> null */
export function addressHint(p: { base_url?: string }): string | null {
  if (!p.base_url) return null;
  return "change it in Settings → Providers";
}

/** The computer and port of an address, to name it in a row's one-line summary.
 *    "http://localhost:1235/v1"       -> "localhost:1235"
 *    "https://studio.local/v1"        -> "studio.local"
 *    "not an address"                 -> "not an address" (shown as typed) */
export function hostAndPort(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

/** Whether a built-in provider sits somewhere other than its own address (so "Reset to default" has something to do).
 *    LM Studio at http://localhost:1235/v1, default :1234 -> true
 *    LM Studio at its default, or a custom provider       -> false */
export function movedAddress(p: ProviderInfo): boolean {
  if (!p.default_url || !p.base_url) return false;
  return p.base_url !== p.default_url;
}

/** Whether Settings may change this provider's address. A custom one always; a built-in one unless Odie's environment
 *  sets it (that would win over what the app saves).
 *    custom "Work box"                     -> true
 *    LM Studio, address_from_env false     -> true
 *    Ollama with OLLAMA_BASE_URL exported  -> false (shown, not editable) */
export function addressEditable(p: ProviderInfo): boolean {
  if (p.kind === "custom") return true;
  return !p.address_from_env;
}

/** The line under the address saying whether the provider answers there.
 *    null (not asked yet)                         -> ""
 *    {ok: true, models: 12}                       -> "Answers · 12 models"
 *    {ok: true, models: 1}                        -> "Answers · 1 model"
 *    {ok: true, models: 0}                        -> "Answers · no chat models loaded"
 *    {ok: false, problem: "Nothing answers ..."}  -> "Nothing answers ..." */
export function answerLine(check: AddressCheck | null): string {
  if (!check) return "";
  if (!check.ok) return check.problem ?? "It doesn't answer.";
  if (!check.models) return "Answers · no chat models loaded";
  return `Answers · ${check.models} ${check.models === 1 ? "model" : "models"}`;
}

/** Whether pressing Save should first ask the typed address, rather than save straight away. Only a changed address
 *  is asked, and once it was asked and didn't answer, the next press saves anyway (the server may just be off now).
 *    address unchanged                              -> false (save)
 *    address changed, not tested yet                -> true  (test first)
 *    address changed, tested, didn't answer         -> false ("Save anyway")
 *    address changed, tested, answers               -> false (save) */
export function shouldTestBeforeSave(draftUrl: string, savedUrl: string, testedUrl: string | null): boolean {
  const changed = draftUrl.trim().replace(/\/+$/, "") !== savedUrl;
  if (!changed) return false;
  return testedUrl !== draftUrl.trim();
}

export type Creativity = { value: number; default: number; min: number; max: number; step: number };

/** The Creativity slider's reading: the temperature and a word for it, e.g. "0.7 · balanced". */
export function creativityLabel(temperature: number): string {
  let word = "balanced";
  if (temperature < 0.4) word = "steady";
  if (temperature > 0.9) word = "inventive";
  return `${temperature.toFixed(1)} · ${word}`;
}
