export type Usage = { input: number; cached: number; output: number; model?: string | null; at?: string };
export type ReplyUsage = { input: number; cached: number; output: number };  // one reply's own counts (the model call that made it)

function tokens(n: number): string {
  return n >= 1000 ? `${Math.round(n / 100) / 10}K`.replace(".0K", "K") : String(n);
}

/** "91% from cache", or "none from cache" when the provider read nothing from it. */
function share(u: ReplyUsage): string {
  return u.cached ? `${Math.round((u.cached / u.input) * 100)}% from cache` : "none from cache";
}

/** "Last reply: 9.8K tokens in, 91% from cache": whether the provider's prompt cache is working (Settings → Brain). */
export function usageLine(u: Usage | null): string {
  if (!u || !u.input) return "";
  return `Last reply: ${tokens(u.input)} tokens in, ${share(u)}`;
}

/** Under a reply, faintly: "9.8K tokens in · 91% from cache"; "" when the reply carries no counts (an older one, a fake). */
export function replyLine(u: ReplyUsage | null | undefined): string {
  if (!u || !u.input) return "";
  return `${tokens(u.input)} tokens in · ${share(u)}`;
}
