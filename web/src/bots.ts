/** Bots (odie/workers/bots.py): named background helpers. The chief makes most of them; Settings → Bots changes any
 * bot's role, prompt, powers and model. Questions a bot waits on (a tap, a sign-in) are answered on Today. */

export type BotModel = { provider: string; model: string } | null;
export type Bot = { name: string; role: string; prompt: string; model: BotModel; powers: string[]; made_by: string; edited_by_user: boolean; chief: boolean;
  look?: { shape: string; color: string; eyes: string };
  // How it stands now (odie/workers/convs.py list_row): its latest conversation, at work, waiting on your tap, unread.
  conversation?: string | null; preview?: string; updated_at?: string | null; working?: boolean; live?: string; needs_you?: boolean; ask?: string; unread?: boolean };
export type Conversation = { id: string; bot: string; title: string; origin: string; preview: string; unread: number; created_at: string; updated_at: string };
export type ConvMessage = { id: number; role: "user" | "bot" | "ask" | "note"; text: string; job_id: string; ts: string;
  media: null | { ask?: string; kind?: "tap" | "sign_in"; why?: string | null; status?: string; card?: { tab?: string; site?: string; url?: string } | null } | Record<string, unknown>[] };
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

/** The list's order: the chief first, then bots that wait on your tap, then the latest at work or talked to; a bot
 * never talked to sorts by name at the end. */
export function sortBots(bots: Bot[]): Bot[] {
  const rank = (b: Bot) => (b.chief ? 0 : b.needs_you ? 1 : 2);
  return [...bots].sort((a, b) => rank(a) - rank(b) || (b.updated_at ?? "").localeCompare(a.updated_at ?? "") || a.name.localeCompare(b.name));
}

/** A row's last line: the question it waits on, else what it is doing now, else the last message, else a hello from
 * its role. needs_you -> "Add 1 item to the cart?"; working -> "reading zigwheels.com…"; new -> "I'm researcher: …". */
export function rowLine(b: Bot): string {
  if (b.needs_you && b.ask) return b.ask;
  if (b.working) return `${b.live || "working"}…`;
  if (b.preview) return b.preview;
  return `I'm ${b.name}: ${b.role.charAt(0).toLowerCase()}${b.role.slice(1)}`;
}

/** A time for the list: today -> "2:17 PM"; yesterday -> "Yesterday"; earlier -> "12 Nov"; none -> "". */
export function whenWords(iso: string | null | undefined, now: Date = new Date(), locale?: string): string {
  if (!iso) return "";
  const t = new Date(iso);
  if (Number.isNaN(t.getTime())) return "";
  const day = (d: Date) => `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
  if (day(t) === day(now)) return t.toLocaleTimeString(locale, { hour: "numeric", minute: "2-digit" });
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (day(t) === day(yesterday)) return "Yesterday";
  return t.toLocaleDateString(locale, { day: "numeric", month: "short" });
}

/** Search the list: a bot whose name, role or last line has the words. "" -> every bot. */
export function matches(b: Bot, q: string): boolean {
  const words = q.trim().toLowerCase();
  if (!words) return true;
  return [b.name, b.role, b.preview ?? ""].some((x) => x.toLowerCase().includes(words));
}

/** Where a bot opens: its latest conversation, or the bot alone (a new conversation starts on the first message).
 * {name: "chief", conversation: "conv-1"} -> "#bot/chief/conv-1"; none yet -> "#bot/chief". */
export function botHref(b: Pick<Bot, "name" | "conversation">): string {
  return b.conversation ? `#bot/${b.name}/${b.conversation}` : `#bot/${b.name}`;
}

/** The bot and conversation a #bot/... address names: "#bot/chief/conv-1" -> {bot: "chief", conv: "conv-1"};
 * "#bot/chief" -> {bot: "chief", conv: null}; anything else -> null. */
export function botFromHash(hash: string): { bot: string; conv: string | null } | null {
  const m = /^#?bot\/([a-z][a-z0-9-]{1,23})(?:\/(conv-[0-9a-f]+))?$/.exec(hash.split("?")[0]);
  if (!m) return null;
  return { bot: m[1], conv: m[2] ?? null };
}
