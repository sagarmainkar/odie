import { firstText, type Trail } from "./fields";

export type SourceBlock = { type: "source"; text: string; url?: string };

/**
 * source: one small line saying where the data came from, linked when there is an http(s) url. Models also write
 * {sources: [{name, url}]}: that becomes one line of names, linked to the first url.
 *   {type: "source", sources: [{name: "ixigo", url: "https://www.ixigo.com/x"}, {name: "Wikipedia"}]}
 *   → {type: "source", text: "ixigo · Wikipedia", url: "https://www.ixigo.com/x"}
 * Dropped: no text and no named source. A javascript: or other non-http link is left off (the text stays).
 */
export function readSource(raw: any, here: Trail): SourceBlock | null {
  const named: any[] = [];
  if (Array.isArray(raw.sources)) {
    for (const s of raw.sources) if (s && firstText([s.name, s.title])) named.push(s);
  }
  let text = typeof raw.text === "string" ? raw.text : "";
  if (!text) text = named.map((s) => firstText([s.name, s.title])).join(" · ");
  if (!text) return here.drop("source needs text");

  const candidates = [raw.url, ...named.map((s) => s.url)];
  const url = candidates.find((u) => typeof u === "string" && /^https?:\/\//.test(u));
  if (url) return { type: "source", text, url };
  return { type: "source", text };
}
