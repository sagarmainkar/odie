import { useCallback, useEffect, useState } from "react";
import { getJSON } from "../api";
import { POWER_WORDS, madeWords, modelChoices, modelFrom, modelValue, modelWords, type Bot, type ModelChoice } from "../bots";
import { Tile } from "./Tile";

async function call(url: string, method: string, body?: unknown): Promise<{ ok: boolean; data: any }> {
  const r = await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
  return { ok: r.ok, data: await r.json().catch(() => ({})) };
}

type Providers = { id: string; name: string; models: { id: string }[]; error: string | null }[];

/** Settings → Bots: the team. Each bot opens to its role, prompt, powers and model; Save makes it yours (the chief
 * no longer changes it). The chief stays; others can go. Hidden while workers are off (the route answers 404). */
export function BotsSection() {
  const [bots, setBots] = useState<Bot[] | null>(null);
  const [powers, setPowers] = useState<string[]>([]);
  const [providers, setProviders] = useState<Providers>([]);
  const [open, setOpen] = useState<string | null>(null);

  const load = useCallback(() => {
    getJSON<{ bots: Bot[]; powers: string[] }>("/api/bots").then((r) => { setBots(r.bots); setPowers(r.powers); }).catch(() => setBots(null));
  }, []);
  useEffect(() => {
    load();
    getJSON<{ providers: Providers }>("/api/models").then((r) => setProviders(r.providers)).catch(() => {});
  }, [load]);
  if (!bots) return null;

  return (
    <section className="flex flex-col gap-2">
      <div className="px-1 text-[13px] font-semibold text-muted">Bots</div>
      <div className="glass rounded-[26px] overflow-hidden">
        {bots.map((b) => (
          <div key={b.name} className="border-b border-line last:border-b-0">
            <button onClick={() => setOpen(open === b.name ? null : b.name)} aria-expanded={open === b.name}
              className="w-full text-left flex items-center gap-3 px-4 min-h-[60px] active:bg-well">
              <Tile icon={b.chief ? "spark" : "brain"} color={b.chief ? "violet" : "blue"} />
              <div className="flex-1 min-w-0">
                <div className="text-[15px] leading-5 truncate">{b.name}</div>
                <div className="text-[12.5px] leading-4 text-muted truncate">{b.role}</div>
              </div>
              <div className="text-[12px] text-muted shrink-0 text-right">{modelWords(b.model)}<br />{madeWords(b)}</div>
            </button>
            {open === b.name && (
              <BotEditor bot={b} powers={powers} choices={modelChoices(providers, b.model)}
                onDone={() => { setOpen(null); load(); }} />
            )}
          </div>
        ))}
      </div>
      <div className="px-1.5 text-[12.5px] text-muted">Say "@chief …" in the chat to give the team a job. The chief makes the bots it needs.</div>
    </section>
  );
}

export function BotEditor({ bot, powers, choices, onDone }: { bot: Bot; powers: string[]; choices: ModelChoice[]; onDone: () => void }) {
  const [role, setRole] = useState(bot.role);
  const [prompt, setPrompt] = useState(bot.prompt);
  const [picked, setPicked] = useState<string[]>(bot.powers);
  const [model, setModel] = useState(modelValue(bot.model));
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const toggle = (p: string) => setPicked((now) => (now.includes(p) ? now.filter((x) => x !== p) : [...now, p]));
  async function save() {
    setBusy(true); setError("");
    const r = await call(`/api/bots/${bot.name}`, "PUT", { role, prompt, powers: picked, model: modelFrom(model), model_given: true });
    setBusy(false);
    if (!r.ok) { setError(r.data.detail || "Couldn't save."); return; }
    onDone();
  }
  async function remove() {
    if (!confirm(`Delete ${bot.name}? Its folder and its jobs' record stay.`)) return;
    const r = await call(`/api/bots/${bot.name}`, "DELETE");
    if (!r.ok) { setError(r.data.detail || "Couldn't delete."); return; }
    onDone();
  }

  const field = "w-full rounded-[14px] border border-line-2 bg-transparent px-3 py-2 text-[14px]";
  return (
    <div className="px-4 pb-4 flex flex-col gap-3 text-[14px]">
      <label className="flex flex-col gap-1"><span className="text-[12.5px] text-muted">Role</span>
        <input className={field} value={role} onChange={(e) => setRole(e.target.value)} maxLength={160} /></label>
      <label className="flex flex-col gap-1"><span className="text-[12.5px] text-muted">Instructions</span>
        <textarea className={`${field} min-h-[120px]`} value={prompt} onChange={(e) => setPrompt(e.target.value)} maxLength={4000} /></label>
      <label className="flex flex-col gap-1"><span className="text-[12.5px] text-muted">Model</span>
        <select className={`${field} h-11`} value={model} onChange={(e) => setModel(e.target.value)}>
          {choices.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
        </select></label>
      <div className="flex flex-col gap-1"><span className="text-[12.5px] text-muted">May use</span>
        {powers.map((p) => (
          <label key={p} className="flex items-center gap-2 min-h-[36px]">
            <input type="checkbox" checked={picked.includes(p)} onChange={() => toggle(p)} />
            <span>{POWER_WORDS[p] ?? p}</span>
          </label>
        ))}
      </div>
      {error && <div className="text-[13px] text-ember-text">{error}</div>}
      <div className="flex gap-2">
        <button disabled={busy} onClick={() => void save()} className="h-11 px-4 rounded-[14px] bg-ember text-on-ember font-semibold">Save</button>
        {!bot.chief && <button onClick={() => void remove()} className="pill h-11 px-4">Delete</button>}
      </div>
    </div>
  );
}
