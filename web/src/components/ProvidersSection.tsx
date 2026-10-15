import { useCallback, useEffect, useState } from "react";
import { getJSON } from "../api";
import { KEY_PAGES, providerSub, type ProviderInfo } from "../providers";
import { Collapse } from "./Collapse";
import { Tile, type IconName, type TileColor } from "./Tile";

const LOOK: Record<string, { icon: IconName; color: TileColor }> = {
  lmstudio: { icon: "brain", color: "ink" }, ollama: { icon: "brain", color: "ink" },
  openai: { icon: "spark", color: "green" }, openrouter: { icon: "globe", color: "blue" },
  gemini: { icon: "spark", color: "blue" }, anthropic: { icon: "spark", color: "orange" },
};

async function send(url: string, method: string, body?: unknown): Promise<string | null> {
  const r = await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  if (r.ok) return null;
  try { const j = await r.json(); return typeof j.detail === "string" ? j.detail : `Failed (${r.status})`; } catch { return `Failed (${r.status})`; }
}

const input = "h-11 px-3 rounded-[14px] bg-well border border-line outline-none text-[15px] focus:border-line-2";

/** Settings: the model providers Odie can use. Cloud presets switch on with a key; keys stay on this computer. */
export function ProvidersSection() {
  const [rows, setRows] = useState<ProviderInfo[] | null>(null);
  const [open, setOpen] = useState<string | null>(null);   // a row's id, or "new" for a custom endpoint
  const [key, setKey] = useState("");
  const [custom, setCustom] = useState({ name: "", base_url: "", api_key: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => getJSON<{ providers: ProviderInfo[] }>("/api/providers").then((d) => setRows(d.providers)).catch(() => {}), []);
  useEffect(() => { void load(); }, [load]);

  function toggle(id: string) { setOpen(open === id ? null : id); setKey(""); setError(""); }
  async function run(fn: () => Promise<string | null>) {
    setBusy(true); setError("");
    const err = await fn();
    setBusy(false);
    if (err) { setError(err); return; }
    setOpen(null); setKey(""); setCustom({ name: "", base_url: "", api_key: "" }); void load();
  }

  return (
    <Collapse title="Providers" summary={rows ? `${rows.filter((r) => r.connected).length} on` : undefined}>
      <div className="glass rounded-[26px] overflow-hidden">
        {rows === null && <div className="px-4 py-3.5 text-[14px] text-muted">Loading…</div>}
        {rows?.map((p) => {
          const look = LOOK[p.id] ?? { icon: "globe" as IconName, color: "violet" as TileColor };
          const tappable = p.kind !== "local";
          return (
            <div key={p.id} className="border-b border-line">
              <button type="button" disabled={!tappable} onClick={() => toggle(p.id)} className="w-full flex items-center gap-3 px-4 py-3 text-left">
                <Tile icon={look.icon} color={look.color} small />
                <span className="flex-1 min-w-0">
                  <b className="block text-[15px] font-semibold">{p.name}</b>
                  <span className="block text-[13px] leading-[18px] text-muted truncate">{providerSub(p)}</span>
                </span>
                <span className={`chip shrink-0 ${p.connected ? "chip-good" : "chip-soft"}`}>{p.kind === "local" ? (p.connected ? "Local" : "Off") : p.connected ? "On" : "Add key"}</span>
              </button>
              {open === p.id && p.kind === "preset" && (
                <div className="px-4 pb-3.5 flex flex-col gap-2.5">
                  {!p.from_env && (
                    <>
                      <input value={key} onChange={(e) => setKey(e.target.value)} type="password" placeholder={p.connected ? "Paste a new key to replace it" : `${p.name} API key`}
                        autoCapitalize="none" autoCorrect="off" className={input} />
                      <a href={KEY_PAGES[p.id]} target="_blank" rel="noreferrer" className="self-start text-[13px] text-ember-text font-semibold">Get a key from {p.name} ↗</a>
                    </>
                  )}
                  {error && <div className="text-[13px] text-warn-ink">{error}</div>}
                  <div className="flex gap-2">
                    {!p.from_env && <button disabled={busy || !key.trim()} onClick={() => run(() => send(`/api/providers/${p.id}/key`, "PUT", { api_key: key.trim() }))}
                      className="pill pill-solid h-10 text-[14px] shadow-none">{busy ? "Checking…" : "Save"}</button>}
                    <button onClick={() => toggle(p.id)} className="pill h-10 text-[14px] shadow-none">Cancel</button>
                    {p.connected && !p.from_env && (
                      <button disabled={busy} onClick={() => { if (confirm(`Remove the ${p.name} key?`)) void run(() => send(`/api/providers/${p.id}/key`, "DELETE")); }}
                        className="ml-auto text-[13.5px] font-semibold text-warn-ink">Remove key</button>
                    )}
                  </div>
                  <div className="text-[12px] leading-4 text-muted">The key stays on this computer. Picking one of its models in Brain sends prompts, mail and memory to {p.name}.</div>
                </div>
              )}
              {open === p.id && p.kind === "custom" && (
                <div className="px-4 pb-3.5 flex gap-2">
                  <button onClick={() => toggle(p.id)} className="pill h-10 text-[14px] shadow-none">Cancel</button>
                  <button disabled={busy} onClick={() => { if (confirm(`Remove ${p.name}?`)) void run(() => send(`/api/models/providers/${p.id}`, "DELETE")); }}
                    className="ml-auto text-[13.5px] font-semibold text-warn-ink">Remove</button>
                </div>
              )}
            </div>
          );
        })}
        {open === "new" ? (
          <div className="px-4 py-3.5 flex flex-col gap-2.5">
            <div className="text-[14px] font-semibold">Other (OpenAI-compatible)</div>
            <input value={custom.name} onChange={(e) => setCustom({ ...custom, name: e.target.value })} placeholder="Name, e.g. My server" className={input} />
            <input value={custom.base_url} onChange={(e) => setCustom({ ...custom, base_url: e.target.value })} placeholder="https://host/v1" autoCapitalize="none" autoCorrect="off" className={input} />
            <input value={custom.api_key} onChange={(e) => setCustom({ ...custom, api_key: e.target.value })} type="password" placeholder="API key (optional)" autoCapitalize="none" autoCorrect="off" className={input} />
            {error && <div className="text-[13px] text-warn-ink">{error}</div>}
            <div className="flex gap-2">
              <button disabled={busy || !custom.name || !custom.base_url}
                onClick={() => run(() => send("/api/models/providers", "POST", { name: custom.name, base_url: custom.base_url, api_key: custom.api_key || null }))}
                className="pill pill-solid h-10 text-[14px] shadow-none">Add</button>
              <button onClick={() => toggle("new")} className="pill h-10 text-[14px] shadow-none">Cancel</button>
            </div>
          </div>
        ) : (
          <div className="px-4 py-3"><button onClick={() => toggle("new")} className="pill pill-flat h-10 text-[14px]">Other (OpenAI-compatible)</button></div>
        )}
      </div>
    </Collapse>
  );
}
