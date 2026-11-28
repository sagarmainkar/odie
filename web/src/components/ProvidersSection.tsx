import { useCallback, useEffect, useState } from "react";
import { getJSON, postJSON } from "../api";
import { KEY_PAGES, addressEditable, answerLine, movedAddress, providerSub, shouldTestBeforeSave, type AddressCheck, type ProviderInfo } from "../providers";
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

/** Asks the server whether the provider answers: at its address now (no url), or at one being typed. */
async function askAddress(id: string, url?: string, apiKey?: string): Promise<AddressCheck> {
  try {
    return await postJSON<AddressCheck>(`/api/providers/${id}/check`, { base_url: url || null, api_key: apiKey || null });
  } catch (e) {
    return { ok: false, models: null, problem: e instanceof Error ? e.message : "Couldn't ask." };
  }
}

const input = "h-11 px-3 rounded-control bg-well border border-line outline-none text-body focus:border-line-2 min-w-0";
const label = "text-caption leading-4 font-semibold text-muted";

/** Settings: the model providers Odie can use. Every row opens to its settings: its address (with a Test), its key,
 *  and Remove or Reset to default. Keys stay on this computer. */
export function ProvidersSection() {
  const [rows, setRows] = useState<ProviderInfo[] | null>(null);
  const [open, setOpen] = useState<string | null>(null);   // a row's id, or "new" for a custom endpoint

  const load = useCallback(() => getJSON<{ providers: ProviderInfo[] }>("/api/providers").then((d) => setRows(d.providers)).catch(() => {}), []);
  useEffect(() => { void load(); }, [load]);

  function toggle(id: string) { setOpen(open === id ? null : id); }
  function done() { setOpen(null); void load(); }

  return (
    <Collapse title="Providers" summary={rows ? `${rows.filter((r) => r.connected).length} on` : undefined}>
      <div className="glass rounded-card overflow-hidden">
        {rows === null && <div className="px-4 py-3.5 text-ui text-muted">Loading…</div>}
        {rows?.map((p) => {
          const look = LOOK[p.id] ?? { icon: "globe" as IconName, color: "violet" as TileColor };
          return (
            <div key={p.id} className="border-b border-line">
              <button type="button" onClick={() => toggle(p.id)} aria-expanded={open === p.id} className="w-full flex items-center gap-3 px-4 py-3 text-left">
                <Tile icon={look.icon} color={look.color} small />
                <span className="flex-1 min-w-0">
                  <b className="block text-body font-semibold">{p.name}</b>
                  <span className="block text-small leading-[18px] text-muted truncate">{providerSub(p)}</span>
                </span>
                <span className={`chip shrink-0 ${p.connected ? "chip-good" : "chip-soft"}`}>{p.kind === "local" ? (p.connected ? "Local" : "Off") : p.connected ? "On" : "Add key"}</span>
              </button>
              {open === p.id && <ProviderPanel key={p.id} p={p} onClose={() => setOpen(null)} onSaved={done} />}
            </div>
          );
        })}
        {open === "new" ? (
          <NewProvider onClose={() => setOpen(null)} onSaved={done} />
        ) : (
          <div className="px-4 py-3"><button onClick={() => toggle("new")} className="pill pill-flat h-10 text-ui">Other (OpenAI-compatible)</button></div>
        )}
      </div>
    </Collapse>
  );
}

/** The opened row: address (editable unless the environment fixes it), whether it answers, the key, and the way out
 *  (Remove for a custom provider or a saved key, Reset to default for a built-in one that was moved). */
function ProviderPanel({ p, onClose, onSaved }: { p: ProviderInfo; onClose: () => void; onSaved: () => void }) {
  const saved = p.base_url ?? "";
  const [url, setUrl] = useState(saved);
  const [name, setName] = useState(p.name);
  const [key, setKey] = useState("");
  const [check, setCheck] = useState<AddressCheck | null>(null);
  // On opening it asks whether the provider answers where it is now; a cloud preset without a key isn't asked (it
  // would only say "wants a key").
  const asksOnOpen = !(p.kind === "preset" && !p.connected);
  const [checking, setChecking] = useState(asksOnOpen);
  const [tested, setTested] = useState<string | null>(null);   // the typed address the last Test asked
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const editable = addressEditable(p);
  const urlChanged = url.trim().replace(/\/+$/, "") !== saved;
  const nameChanged = p.kind === "custom" && name.trim() !== p.name;
  const keyTyped = key.trim() !== "";
  const dirty = urlChanged || nameChanged || keyTyped;
  const failedHere = tested === url.trim() && check !== null && !check.ok;
  const canRemove = p.kind === "custom" || (p.kind === "preset" && p.connected && !p.from_env);
  const canReset = p.kind !== "custom" && editable && movedAddress(p);

  useEffect(() => {
    if (!asksOnOpen) return;
    let live = true;
    void askAddress(p.id).then((c) => { if (live) { setCheck(c); setChecking(false); } });
    return () => { live = false; };
  }, [p.id, asksOnOpen]);

  async function test(): Promise<AddressCheck> {
    setChecking(true); setError("");
    const typed = url.trim();
    const c = await askAddress(p.id, urlChanged ? typed : undefined, key.trim() || undefined);
    setCheck(c); setTested(typed); setChecking(false);
    return c;
  }

  async function act(fn: () => Promise<string | null>) {
    setBusy(true); setError("");
    const err = await fn();
    setBusy(false);
    if (err) { setError(err); return; }
    onSaved();
  }

  async function save() {
    if (shouldTestBeforeSave(url, saved, tested)) {
      const c = await test();
      if (!c.ok) return;   // the problem shows; the button now says "Save anyway"
    }
    await act(async () => {
      if (p.kind === "custom") {
        return send(`/api/models/providers/${p.id}`, "PUT", { name: name.trim(), base_url: url.trim(), api_key: key.trim() || null });
      }
      if (urlChanged) {
        const err = await send(`/api/providers/${p.id}/address`, "PUT", { base_url: url.trim() });
        if (err) return err;
      }
      if (keyTyped) return send(`/api/providers/${p.id}/key`, "PUT", { api_key: key.trim() });
      return null;
    });
  }

  function remove() {
    if (p.kind === "custom") return act(() => send(`/api/models/providers/${p.id}`, "DELETE"));
    return act(() => send(`/api/providers/${p.id}/key`, "DELETE"));
  }

  let keyPlaceholder = `${p.name} API key`;
  if (p.kind === "custom") keyPlaceholder = p.has_key ? "Key saved · paste a new key to replace it" : "API key (optional)";
  else if (p.connected) keyPlaceholder = "Key saved · paste a new key to replace it";
  let saveLabel = "Save";
  if (failedHere && urlChanged) saveLabel = "Save anyway";
  if (busy) saveLabel = "Saving…";
  if (checking && !busy) saveLabel = "Checking…";
  const answer = answerLine(check);

  return (
    <div className="px-4 pb-3.5 flex flex-col gap-2.5">
      {p.kind === "custom" && (
        <label className="flex flex-col gap-1">
          <span className={label}>Name</span>
          <input value={name} onChange={(e) => setName(e.target.value)} className={input} />
        </label>
      )}
      <label className="flex flex-col gap-1">
        <span className={label}>Address</span>
        {editable ? (
          <input value={url} onChange={(e) => { setUrl(e.target.value); setCheck(null); setTested(null); }} placeholder={p.default_url ?? "http://host:port/v1"}
            autoCapitalize="none" autoCorrect="off" spellCheck={false} inputMode="url" className={`${input} font-mono text-ui`} />
        ) : (
          <span className="text-ui font-mono [overflow-wrap:anywhere]">{saved}</span>
        )}
      </label>
      {!editable && <div className="text-caption leading-4 text-muted">Set in Odie's environment, so it's changed there, not here.</div>}
      <div className="flex items-center gap-2 min-h-8">
        {checking ? <span className="spinner shrink-0" /> : check && <span className={`w-2 h-2 rounded-full shrink-0 ${check.ok ? "bg-good" : "bg-gold"}`} />}
        <span className={`flex-1 min-w-0 text-small leading-[18px] ${check && !check.ok ? "text-warn-ink" : "text-muted"}`}>
          {checking ? "Asking…" : answer || (urlChanged ? "Test asks the new address before you save." : "")}
        </span>
        <button type="button" disabled={checking || busy || !url.trim()} onClick={() => void test()} className="pill pill-flat h-8 text-small shrink-0">Test</button>
      </div>
      {p.kind === "custom" && (
        <label className="flex flex-col gap-1">
          <span className={label}>Key</span>
          <input value={key} onChange={(e) => setKey(e.target.value)} type="password" placeholder={keyPlaceholder} autoCapitalize="none" autoCorrect="off" className={input} />
        </label>
      )}
      {p.kind === "preset" && !p.from_env && (
        <label className="flex flex-col gap-1">
          <span className={label}>Key</span>
          <input value={key} onChange={(e) => setKey(e.target.value)} type="password" placeholder={keyPlaceholder} autoCapitalize="none" autoCorrect="off" className={input} />
          <a href={KEY_PAGES[p.id]} target="_blank" rel="noreferrer" className="self-start pt-1 text-small text-ember-text font-semibold">Get a key from {p.name} ↗</a>
        </label>
      )}
      {p.kind === "preset" && p.from_env && <div className="text-caption leading-4 text-muted">The key is set in Odie's environment.</div>}
      {error && <div className="text-small text-warn-ink">{error}</div>}
      {confirming ? (
        <div className="rounded-control bg-warn-tint px-3 py-2.5 flex flex-wrap items-center gap-2">
          <span className="flex-1 min-w-[12rem] text-small leading-[18px] text-warn-ink">
            {p.kind === "custom" ? `Remove ${p.name}? A brain that uses it goes back to the default model.` : `Remove the ${p.name} key? Its models stop working until you add one again.`}
          </span>
          <button type="button" disabled={busy} onClick={() => void remove()} className="pill pill-solid h-9 text-ui shadow-none">{busy ? "Removing…" : "Remove"}</button>
          <button type="button" onClick={() => setConfirming(false)} className="pill h-9 text-ui shadow-none">Keep</button>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          {(editable || p.kind !== "local") && (
            <button type="button" disabled={busy || checking || !dirty || !url.trim()} onClick={() => void save()} className="pill pill-solid h-10 text-ui shadow-none">{saveLabel}</button>
          )}
          <button type="button" onClick={onClose} className="pill h-10 text-ui shadow-none">{dirty ? "Cancel" : "Close"}</button>
          <span className="flex-1" />
          {canReset && (
            <button type="button" disabled={busy} onClick={() => void act(() => send(`/api/providers/${p.id}/address`, "DELETE"))} className="pill h-10 text-ui shadow-none">Reset to default</button>
          )}
          {canRemove && (
            <button type="button" disabled={busy} onClick={() => setConfirming(true)} className="pill h-10 text-ui shadow-none text-warn-ink">{p.kind === "custom" ? "Remove" : "Remove key"}</button>
          )}
        </div>
      )}
      {canReset && <div className="text-caption leading-4 text-muted">Its own address is {p.default_url}.</div>}
      {p.kind === "preset" && <div className="text-caption leading-4 text-muted">The key stays on this computer. Picking one of its models in Brain sends prompts, mail and memory to {p.name}.</div>}
    </div>
  );
}

/** Adding a custom OpenAI-compatible provider: name, address (with a Test) and an optional key. */
function NewProvider({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [custom, setCustom] = useState({ name: "", base_url: "", api_key: "" });
  const [check, setCheck] = useState<AddressCheck | null>(null);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function test() {
    setChecking(true);
    setCheck(await askAddress("new", custom.base_url.trim(), custom.api_key.trim() || undefined));
    setChecking(false);
  }
  async function add() {
    setBusy(true); setError("");
    const err = await send("/api/models/providers", "POST", { name: custom.name.trim(), base_url: custom.base_url.trim(), api_key: custom.api_key.trim() || null });
    setBusy(false);
    if (err) { setError(err); return; }
    onSaved();
  }
  function edit(change: Partial<typeof custom>) {
    setCustom({ ...custom, ...change });
    if (change.base_url !== undefined) setCheck(null);
  }

  return (
    <div className="px-4 py-3.5 flex flex-col gap-2.5">
      <div className="text-ui font-semibold">Other (OpenAI-compatible)</div>
      <input value={custom.name} onChange={(e) => edit({ name: e.target.value })} placeholder="Name, e.g. My server" className={input} />
      <input value={custom.base_url} onChange={(e) => edit({ base_url: e.target.value })} placeholder="https://host/v1" autoCapitalize="none" autoCorrect="off" spellCheck={false} inputMode="url" className={`${input} font-mono text-ui`} />
      <input value={custom.api_key} onChange={(e) => edit({ api_key: e.target.value })} type="password" placeholder="API key (optional)" autoCapitalize="none" autoCorrect="off" className={input} />
      <div className="flex items-center gap-2 min-h-8">
        {checking ? <span className="spinner shrink-0" /> : check && <span className={`w-2 h-2 rounded-full shrink-0 ${check.ok ? "bg-good" : "bg-gold"}`} />}
        <span className={`flex-1 min-w-0 text-small leading-[18px] ${check && !check.ok ? "text-warn-ink" : "text-muted"}`}>{checking ? "Asking…" : answerLine(check)}</span>
        <button type="button" disabled={checking || !custom.base_url.trim()} onClick={() => void test()} className="pill pill-flat h-8 text-small shrink-0">Test</button>
      </div>
      {error && <div className="text-small text-warn-ink">{error}</div>}
      <div className="flex gap-2">
        <button disabled={busy || !custom.name.trim() || !custom.base_url.trim()} onClick={() => void add()} className="pill pill-solid h-10 text-ui shadow-none">Add</button>
        <button onClick={onClose} className="pill h-10 text-ui shadow-none">Cancel</button>
      </div>
    </div>
  );
}
