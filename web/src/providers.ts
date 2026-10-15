export type ProviderInfo = { id: string; name: string; kind: "local" | "preset" | "custom"; connected: boolean; base_url?: string; from_env?: boolean };
export type Model = { id: string; local: boolean };

/** Where to get each preset's key (opens in the browser). */
export const KEY_PAGES: Record<string, string> = {
  openai: "https://platform.openai.com/api-keys",
  openrouter: "https://openrouter.ai/keys",
  gemini: "https://aistudio.google.com/apikey",
  anthropic: "https://console.anthropic.com/settings/keys",
};

export function providerSub(p: ProviderInfo): string {
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

/** How to change a provider's address, in plain words under its models on the Brain screen. A built-in provider (LM
 *  Studio, Ollama) moves with a setting the setup guide lists; a custom one is edited in Settings → Providers.
 *    {base_url, base_url_env: "OLLAMA_BASE_URL"} -> "another address: see the setup guide"
 *    {base_url, base_url_env: null}             -> "change it in Settings → Providers"
 *    {} (no address)                            -> null */
export function addressHint(p: { base_url?: string; base_url_env?: string | null }): string | null {
  if (!p.base_url) return null;
  if (p.base_url_env) return "another address: see the setup guide";
  return "change it in Settings → Providers";
}

export type Creativity = { value: number; default: number; min: number; max: number; step: number };

/** The Creativity slider's reading: the temperature and a word for it, e.g. "0.7 · balanced". */
export function creativityLabel(temperature: number): string {
  let word = "balanced";
  if (temperature < 0.4) word = "steady";
  if (temperature > 0.9) word = "inventive";
  return `${temperature.toFixed(1)} · ${word}`;
}
