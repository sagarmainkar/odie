// The sample chat in evals/sample/sample-chat.json (a made-up conversation recorded with evals/sample/record.py), for
// the #sample screen, and the shape every saved chat has (scripts/chat_replay.sh writes the same for its replays in
// evals/chats, which aren't committed). Bundled with the app (one small chunk, fetched only when the screen opens).
import type { ChatReplyScore } from "./chatScore";

export type ChatTool = { tool: string; args?: Record<string, unknown>; hosts?: string[] };

export type ChatTurn = {
  n: number;
  user: string;
  images?: number;  // pictures the user sent with it (imported chats only; not shown)
  reply: string;
  tools: ChatTool[];
  visuals: boolean;
  media: { kind?: string; title?: string }[];
  error: string | null;
  seconds: number;
  tokens: { input: number; output: number };
  score: ChatReplyScore;
};

export type SavedChat = {
  source: "live" | "replay";
  date: string;
  provider: string;
  model: string;
  turns: ChatTurn[];
  totals: { seconds: number; input: number; output: number; errors: number };
  settings?: { thinking?: boolean };  // thinking: the "think longer" toggle was on
};

/**
 * Decides which loaded files are chats the view can show: a file needs a model and a list of turns that were scored
 * (a file written before scoring finished is left out). Live chats come first, then replays by model name.
 *   {"a.json": {source: "replay", model: "claude-opus-5-5", turns: [{…, score: {…}}], …}, "b.json": {turns: []}}
 *   → [the chat from a.json]
 */
export function toChats(files: Record<string, unknown>): SavedChat[] {
  const chats: SavedChat[] = [];
  for (const data of Object.values(files)) {
    const chat = data as Partial<SavedChat> | null;
    if (!chat || typeof chat.model !== "string" || !Array.isArray(chat.turns) || chat.turns.length === 0) continue;
    if (!chat.turns.every((t) => t && typeof t === "object" && "score" in t)) continue;
    chats.push(chat as SavedChat);
  }
  const liveFirst = (c: SavedChat) => (c.source === "live" ? 0 : 1);
  chats.sort((a, b) => liveFirst(a) - liveFirst(b) || a.model.localeCompare(b.model) || b.date.localeCompare(a.date));
  return chats;
}

/** A tool call in a few words for its chip: the arguments that say most, cut short.
 *  {tool: "web_search", args: {query: "Pixel 10a price"}} → "Pixel 10a price";  {tool: "load_skill", args: {skill_name: "visuals"}} → "visuals" */
export function toolDetail(t: ChatTool): string {
  if (t.hosts?.length) return t.hosts.join(" & ");
  const args = t.args ?? {};
  const first = ["query", "skill_name", "title", "url", "content", "text"].map((k) => args[k]).find((v) => typeof v === "string" && v);
  const words = typeof first === "string" ? first : "";
  return words.length > 40 ? `${words.slice(0, 40)}…` : words;
}

/** The sample chat, or null when this build has none. */
export async function loadSample(): Promise<SavedChat | null> {
  const files = import.meta.glob(["../../../../evals/sample/*.json", "!../../../../evals/sample/*.turns.json"], { import: "default" });
  const loaded: Record<string, unknown> = {};
  for (const [path, load] of Object.entries(files)) {
    loaded[path] = await load();
  }
  return toChats(loaded)[0] ?? null;
}
