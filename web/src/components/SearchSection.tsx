import { useCallback, useEffect, useState } from "react";
import { getJSON } from "../api";
import { FREE, inUse, lastNote, searchSub, type SearchInfo } from "../search";
import { Collapse } from "./Collapse";
import { Tile } from "./Tile";

async function send(url: string, method: string, body?: unknown): Promise<string | null> {
  const r = await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  if (r.ok) return null;
  try { const j = await r.json(); return typeof j.detail === "string" ? j.detail : `Failed (${r.status})`; } catch { return `Failed (${r.status})`; }
}

const input = "h-11 px-3 rounded-[14px] bg-well border border-line outline-none text-[15px] focus:border-line-2";

/** Settings: web search. Whichever key is set is used (Tavily, then Brave, then Ollama); with none working, the free
 * fallback (DuckDuckGo, pages read directly) keeps search going. Keys stay on this computer. */
export function SearchSection() {
  const [d, setD] = useState<SearchInfo | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [key, setKey] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => getJSON<SearchInfo>("/api/search").then(setD).catch(() => {}), []);
  useEffect(() => { void load(); }, [load]);

  function toggle(id: string) { setOpen(open === id ? null : id); setKey(""); setError(""); }
  async function run(fn: () => Promise<string | null>) {
    setBusy(true); setError("");
    const err = await fn();
    setBusy(false);
    if (err) { setError(err); return; }
    setOpen(null); setKey(""); void load();
  }

  const using = d ? inUse(d) : null;
  const note = d ? lastNote(d) : "";
  const chip = (on: boolean, id: string) => (using === id ? <span className="chip chip-good shrink-0">In use</span>
    : <span className={`chip shrink-0 ${on ? "chip-soft" : "chip-soft opacity-70"}`}>{on ? "Ready" : "Add key"}</span>);
  return (
    <Collapse title="Web search" summary={d ? (using === FREE ? "Free fallback" : d.providers.find((p) => p.id === using)?.name) : undefined}>
      <div className="glass rounded-[26px] overflow-hidden">
        {d === null && <div className="px-4 py-3.5 text-[14px] text-muted">Loading…</div>}
        {d?.providers.map((p) => (
          <div key={p.id} className="border-b border-line">
            <button type="button" onClick={() => toggle(p.id)} className="w-full flex items-center gap-3 px-4 py-3 text-left">
              <Tile icon="globe" color={p.connected ? "blue" : "ink"} small />
              <span className="flex-1 min-w-0">
                <b className="block text-[15px] font-semibold">{p.name}</b>
                <span className="block text-[13px] leading-[18px] text-muted truncate">{searchSub(p)}</span>
              </span>
              {chip(p.connected, p.id)}
            </button>
            {open === p.id && (
              <div className="px-4 pb-3.5 flex flex-col gap-2.5">
                {p.source !== "env" && (
                  <>
                    <input value={key} onChange={(e) => setKey(e.target.value)} type="password" autoCapitalize="none" autoCorrect="off" className={input}
                      placeholder={p.connected ? "Paste a new key to replace it" : `${p.name} API key`} />
                    <a href={p.key_page} target="_blank" rel="noreferrer" className="self-start text-[13px] text-ember-text font-semibold">Get a key from {p.name} ↗</a>
                  </>
                )}
                {error && <div className="text-[13px] text-warn-ink">{error}</div>}
                <div className="flex gap-2">
                  {p.source !== "env" && <button disabled={busy || !key.trim()} onClick={() => run(() => send(`/api/search/${p.id}/key`, "PUT", { api_key: key.trim() }))}
                    className="pill pill-solid h-10 text-[14px] shadow-none">{busy ? "Checking…" : "Save"}</button>}
                  <button onClick={() => toggle(p.id)} className="pill h-10 text-[14px] shadow-none">Cancel</button>
                  {p.source === "settings" && (
                    <button disabled={busy} onClick={() => { if (confirm(`Remove the ${p.name} key?`)) void run(() => send(`/api/search/${p.id}/key`, "DELETE")); }}
                      className="ml-auto text-[13.5px] font-semibold text-warn-ink">Remove key</button>
                  )}
                </div>
                <div className="text-[12px] leading-4 text-muted">
                  Saving checks the key with one real search. It stays on this computer; searches go to {p.name}.
                </div>
              </div>
            )}
          </div>
        ))}
        {d && (
          <div className="flex items-center gap-3 px-4 py-3">
            <Tile icon="globe" color="ink" small />
            <span className="flex-1 min-w-0">
              <b className="block text-[15px] font-semibold">Free fallback</b>
              <span className="block text-[13px] leading-[18px] text-muted">DuckDuckGo, pages read directly · when no key works</span>
            </span>
            {using === FREE ? <span className="chip chip-good shrink-0">In use</span> : <span className="chip chip-soft shrink-0">Standby</span>}
          </div>
        )}
        {note && <div className="px-4 pb-3 text-[12.5px] leading-[17px] text-warn-ink">{note}</div>}
      </div>
      <div className="px-1 pt-2 text-[12px] leading-4 text-muted">Whichever key is set is used: Tavily first, then Brave, then Ollama. If one fails, the next one takes over.</div>
    </Collapse>
  );
}
