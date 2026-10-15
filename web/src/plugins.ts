export type SkillRow = { name: string; title?: string; summary?: string; description: string; source: "builtin" | "user"; status: string; tools: string[]; reason: string };
export type ServerRow = { name: string; spec: Record<string, any>; status: string; tools: string[]; reason: string; alwaysOn: boolean; enabled: boolean; readsFree: boolean };
export type CheckedTool = { name: string; read_only: boolean; asks: boolean };
export type Check = { ok: true; tools: CheckedTool[] } | { ok: false; reason: string };
export type Preset = { id: string; title: string; where: string; key_label: string };
export type ServerForm = { name: string; title?: string; target: string; description: string; env: [string, string][] };

export function statusLabel(status: string): { text: string; tone: "good" | "warn" | "soft" } {
  return status === "ok" ? { text: "Ready", tone: "good" } : status === "blocked" ? { text: "Needs your OK", tone: "warn" }
    : status === "disabled" ? { text: "Off", tone: "soft" } : status === "failed" ? { text: "Not responding", tone: "warn" }
    : status === "error" ? { text: "Problem", tone: "warn" } : { text: status, tone: "soft" };
}

/** Split a command line like a shell does for quotes: "My Vault" and 'read only' stay one argument. */
export function splitArgs(line: string): string[] {
  const out: string[] = [];
  for (const m of line.matchAll(/"([^"]*)"|'([^']*)'|(\S+)/g)) out.push(m[1] ?? m[2] ?? m[3]);
  return out;
}

export function specFromForm(f: ServerForm): { name: string; spec: Record<string, unknown> } | string {
  const name = f.name.trim();
  if (!/^[a-z0-9][a-z0-9-]*$/.test(name)) return "Use a lower-case name: letters, digits and dashes.";
  const target = f.target.trim();
  if (!target) return "Add a command or a URL.";
  const env = Object.fromEntries(f.env.filter(([k]) => k.trim()).map(([k, v]) => [k.trim(), v]));
  const spec: Record<string, unknown> = /^https?:\/\//.test(target)
    ? { url: target, ...(Object.keys(env).length ? { headers: env } : {}) }
    : { command: splitArgs(target)[0], args: splitArgs(target).slice(1), ...(Object.keys(env).length ? { env } : {}) };
  if (f.title?.trim()) spec.title = f.title.trim();
  if (f.description.trim()) spec.description = f.description.trim();
  return { name, spec };
}

/** "search_notes" -> "Search notes". */
export function toolLabel(name: string): string {
  const words = name.replace(/[_-]+/g, " ").trim().toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** The name people see: the server's title if it has one ("Obsidian notes"), else its config name. */
export function serverTitle(s: Pick<ServerRow, "name" | "spec">): string {
  return (typeof s.spec.title === "string" && s.spec.title.trim()) || s.name;
}

/** The add/edit form filled from a saved server. Secrets arrive masked and are sent back masked, which the
 * server reads as "keep the saved value". */
export function formFromServer(s: Pick<ServerRow, "name" | "spec">): ServerForm {
  const sp = s.spec;
  const target = sp.url ? String(sp.url) : [sp.command, ...(Array.isArray(sp.args) ? sp.args : [])].filter(Boolean)
    .map((a) => (/\s/.test(String(a)) ? `"${a}"` : String(a))).join(" ");
  const secrets = Object.entries((sp.url ? sp.headers : sp.env) || {}) as [string, string][];
  return { name: s.name, title: sp.title || "", target, description: sp.description || "", env: secrets.length ? secrets : [["", ""]] };
}

/** What the connection check found: "12 tools · 4 ask for a tap". */
/** A link with its code in it (?token=…): the code box isn't needed (Odie ignores it). */
export function linkCarriesToken(link: string): boolean {
  try { return [...new URL(link.trim()).searchParams].some(([k, v]) => ["token", "api_key", "apikey", "key", "secret"].includes(k.toLowerCase()) && !!v); }
  catch { return false; }
}

export function checkSummary(tools: CheckedTool[]): string {
  const n = tools.length;
  if (!n) return "No tools";
  const asks = tools.filter((t) => t.asks).length;
  const head = `${n} tool${n > 1 ? "s" : ""}`;
  if (!asks) return `${head} · no taps needed`;
  if (asks === n) return `${head} · ${n > 1 ? "each" : "it"} asks for a tap`;
  return `${head} · ${asks} ask${asks > 1 ? "" : "s"} for a tap`;
}
