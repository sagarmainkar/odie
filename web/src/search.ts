export type SearchRow = { id: string; name: string; connected: boolean; source: "env" | "settings" | null; key_page: string };
export type SearchInfo = { providers: SearchRow[]; next: string; last?: { provider: string; failed: string[]; at: string } | null };

export const FREE = "free";
const NAMES: Record<string, string> = { tavily: "Tavily", brave: "Brave", ollama: "Ollama", free: "the free fallback" };

/** Which one searches now: the one that answered last, else the first with a key, else the free fallback. */
export function inUse(d: SearchInfo): string {
  const last = d.last?.provider;
  return last && (last === FREE || d.providers.some((p) => p.id === last && p.connected)) ? last : d.next;
}

export function searchSub(p: SearchRow): string {
  if (p.source === "settings") return "Key saved in Odie";
  if (p.source === "env") return "Key set in the environment";
  return "Add a key to use it";
}

/** One line about the last search when a provider failed, e.g. "Last search: Tavily quota used up (432) → Brave answered". */
export function lastNote(d: SearchInfo): string {
  const l = d.last;
  if (!l || !l.failed?.length) return "";
  return `Last search: ${l.failed.join("; ")} → ${l.provider === FREE ? "the free fallback answered" : `${NAMES[l.provider] ?? l.provider} answered`}`;
}
