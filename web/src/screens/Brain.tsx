import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { getJSON, postJSON } from "../api";
import { badge, brainState, partLine, said, tone, type BrainReport } from "../brain";
import { Collapse } from "../components/Collapse";
import { addressHint, creativityLabel, visibleModels, type Creativity } from "../providers";
import { usageLine, type Usage } from "../usage";

type ModelRow = { id: string; local: boolean };
type ProviderRow = { id: string; name: string; local: boolean; models: ModelRow[]; error: string | null; base_url?: string; base_url_env?: string | null };
type Sel = { provider: string; model: string; leaves_mini: boolean; chosen?: boolean; reachable?: boolean };
type Data = { providers: ProviderRow[]; selection: { chat: Sel }; creativity?: Creativity };

function Pill({ local, children }: { local: boolean; children?: ReactNode }) {
  return <span className={`chip ${local ? "chip-good" : "chip-warn"}`}>{children ?? (local ? "on this computer" : "leaves this computer")}</span>;
}

function ModelName({ id, className = "" }: { id: string; className?: string }) {
  const i = id.lastIndexOf("/");
  return <span className={`truncate ${className}`}>{i > 0 && <span className="text-dim font-normal">{id.slice(0, i + 1)}</span>}{id.slice(i + 1)}</span>;
}

function CheckCard({ report, checking, onCheck }: { report?: BrainReport; checking: boolean; onCheck: () => void }) {
  const t = report ? tone(report) : null;
  const color = t === "good" ? "text-moss-text" : t === "bad" ? "text-ember-text" : "text-warn-ink";
  return (
    <div className="mt-2 pt-3 border-t border-line flex flex-col gap-1.5">
      {report && !checking && (
        <>
          <div className={`text-[14px] leading-5 font-medium ${color}`} role="status">{said(report)}</div>
          {report.parts.map((p) => <div key={p.name} className="text-[12.5px] leading-[18px] text-muted">{partLine(p)}</div>)}
        </>
      )}
      <button onClick={onCheck} disabled={checking} className="self-start h-9 px-3.5 rounded-full border border-line-2 text-[13.5px] font-medium flex items-center gap-2">
        {checking ? <><span className="spinner" /> Checking… about 30 seconds</> : report ? "Check again" : "Check this model"}
      </button>
    </div>
  );
}

/** Settings → Brain → Creativity: the chat temperature. Saved when the finger lifts (or a key is released), used from
 *  the next message. Claude ignores it: its newer models set their own. */
function CreativityCard({ creativity, isClaude }: { creativity: Creativity; isClaude: boolean }) {
  const [value, setValue] = useState(creativity.value);
  const [saved, setSaved] = useState(creativity.value);  // a new value from the server remounts the card (its key)

  async function save() {
    if (value === saved) return;
    const r = await fetch("/api/models/creativity", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ temperature: value }) });
    if (r.ok) setSaved(value);
  }
  return (
    <div className="glass rounded-[26px] p-4 flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <label htmlFor="creativity" className="text-[13px] leading-5 font-bold text-muted">Creativity</label>
        <span className="text-[13px] leading-5 text-muted tabular-nums">{creativityLabel(value)}</span>
      </div>
      <input id="creativity" type="range" min={creativity.min} max={creativity.max} step={creativity.step} value={value}
        onChange={(e) => setValue(Number(e.target.value))} onPointerUp={save} onKeyUp={save} onBlur={save}
        className="w-full accent-ember" />
      <div className="text-[12.5px] leading-[18px] text-muted">
        {isClaude ? "Claude sets this itself." : `Lower keeps chat steady and factual, higher makes it more varied. Default ${creativity.default.toFixed(1)}.`}
      </div>
    </div>
  );
}

export function Brain() {
  const [data, setData] = useState<Data | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [checks, setChecks] = useState<Record<string, BrainReport>>({});
  const [checking, setChecking] = useState(false);
  const [usage, setUsage] = useState<Usage | null>(null);
  const load = useCallback(() => {
    setFailed(false);
    getJSON<Data>("/api/models").then(setData).catch(() => setFailed(true));
    getJSON<{ usage: Usage | null }>("/api/models/usage").then((r) => setUsage(r.usage)).catch(() => {});
    getJSON<Record<string, BrainReport>>("/api/brain/checks").then(setChecks).catch(() => {});
  }, []);
  useEffect(() => { load(); }, [load]);

  async function checkModel(provider: string, model: string) {
    setChecking(true);
    try {
      const r = await postJSON<BrainReport>("/api/brain/check", { provider, model });
      setChecks((c) => ({ ...c, [`${provider}/${model}`]: r }));
    } catch {
      setChecks((c) => ({ ...c, [`${provider}/${model}`]: { provider, model, verdict: "fail", sentence: `${model}: Couldn't run the check. Try again.`, parts: [], checked_at: "" } }));
    } finally { setChecking(false); }
  }

  async function choose(provider: string, model: string) {
    setBusy(`${provider}/${model}`);
    try {
      const r = await fetch("/api/models/selection", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ slot: "chat", provider, model }) });
      if (r.ok) load();
    } finally { setBusy(null); }
  }
  const current = data?.selection.chat;
  const state = brainState(current?.chosen, current?.reachable);
  const providerName = (id: string) => data?.providers.find((p) => p.id === id)?.name ?? id;

  return (
    <div className="h-full overflow-y-auto no-scrollbar px-[18px] safe-top flex flex-col gap-6 pb-6">
      <div className="flex items-center gap-3">
        <a href="#settings" aria-label="Back" className="pill w-11 px-0">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 6l-6 6 6 6" /></svg>
        </a>
        <div className="text-[21px] font-bold tracking-[-0.015em]">Brain</div>
      </div>

      {current && state === "none" && (
        <div className="glass rounded-[26px] p-4 flex flex-col gap-1">
          <div className="text-[17px] leading-[22px] font-medium">No brain yet</div>
          <div className="flex items-start gap-2 text-[13px] leading-[18px] text-muted">
            <span className="w-1.5 h-1.5 rounded-full bg-gold mt-1.5 shrink-0" />
            Start LM Studio or Ollama with a model and pick it below, or add a key for a cloud model in Settings → Providers.
          </div>
        </div>
      )}
      {current && state !== "none" && (
        <div className="glass rounded-[26px] p-4 flex flex-col gap-1">
          <div className="text-[13px] leading-5 font-bold text-muted">Odie is using</div>
          <ModelName id={current.model} className="text-[17px] leading-[22px] font-medium block" />
          <div className="flex items-center gap-2 text-[13px] leading-[18px] text-muted">
            <span className={`w-1.5 h-1.5 rounded-full ${state === "unreachable" || current.leaves_mini ? "bg-gold" : "bg-moss"}`} />
            {state === "unreachable"
              ? `${providerName(current.provider)} isn't reachable`
              : `${providerName(current.provider)} · ${current.leaves_mini ? "leaves this computer" : "on this computer"}`}
          </div>
          {usageLine(usage) && <div className="text-[13px] leading-[18px] text-muted">{usageLine(usage)}</div>}
          {state === "ready" && <CheckCard report={checks[`${current.provider}/${current.model}`]} checking={checking} onCheck={() => checkModel(current.provider, current.model)} />}
        </div>
      )}

      {data?.creativity && <CreativityCard key={data.creativity.value} creativity={data.creativity} isClaude={current?.provider === "anthropic"} />}

      {!data && !failed && [0, 1].map((k) => (
        <div key={k} className="flex flex-col gap-2">
          <div className="h-3 w-24 rounded bg-surface-2" />
          <div className="glass rounded-[26px] p-4 flex flex-col gap-3">{[1, 2, 3].map((i) => <div key={i} className="h-3.5 rounded-[7px] bg-surface-2" style={{ width: `${90 - i * 12}%` }} />)}</div>
        </div>
      ))}
      {data && data.providers.reduce((n, p) => n + p.models.length, 0) > 15 && (
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Find a model" type="search"
          autoCapitalize="none" autoCorrect="off" className="h-11 px-4 rounded-full bg-well border border-line outline-none text-[15px] focus:border-line-2" />
      )}
      {failed && <div className="text-[14px] text-muted">Couldn't reach the server. <button onClick={load} className="text-ember-text font-medium">Retry</button></div>}

      {data?.providers.map((p) => {
        const { shown, hidden } = visibleModels(p.models, query, expanded[p.id] ? Infinity : 12, current?.provider === p.id ? current.model : undefined);
        if (query.trim() && shown.length === 0) return null;
        return (
        <Collapse key={`${p.id}-${query.trim() ? "q" : ""}`} title={p.name} defaultOpen={!!query.trim() || current?.provider === p.id}
          summary={p.error ? <span>not reachable</span> : <><span>{p.models.length} model{p.models.length === 1 ? "" : "s"}</span><Pill local={p.local} /></>}>
          <div className="glass rounded-[26px] overflow-hidden">
            {p.error && <div className="px-4 py-2 text-[14px] text-muted flex items-center justify-between">Not reachable <button onClick={load} className="h-10 px-3 -mr-3 text-ember-text font-medium">Retry</button></div>}
            {!p.error && p.models.length === 0 && <div className="px-4 py-3 text-[14px] text-muted">No chat models listed</div>}
            {shown.map((m, i) => {
              const on = current?.provider === p.id && current?.model === m.id;
              const isBusy = busy === `${p.id}/${m.id}`;
              return (
                <button key={m.id} onClick={() => choose(p.id, m.id)} disabled={busy !== null}
                  className={`w-full text-left flex items-center gap-3 px-4 min-h-[52px] active:bg-well ${i < shown.length - 1 || hidden ? "border-b border-line" : ""}`}>
                  <span className={`w-2 h-2 rounded-full shrink-0 ${on ? "bg-iris" : "bg-line-2"}`} />
                  <ModelName id={m.id} className={`flex-1 min-w-0 text-[15px] leading-5 ${on ? "font-medium" : ""}`} />
                  {m.local !== p.local && <Pill local={m.local} />}
                  {checks[`${p.id}/${m.id}`] && (
                    <span className={`text-[12px] shrink-0 ${tone(checks[`${p.id}/${m.id}`]) === "good" ? "text-moss-text" : tone(checks[`${p.id}/${m.id}`]) === "bad" ? "text-ember-text" : "text-warn-ink"}`}>
                      {badge(checks[`${p.id}/${m.id}`])}
                    </span>
                  )}
                  {isBusy ? <span className="spinner shrink-0" /> : on ? (
                    <svg className="text-ember-text shrink-0" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><path d="M5 13l4 4L19 7" /></svg>
                  ) : null}
                </button>
              );
            })}
            {hidden > 0 && <button onClick={() => setExpanded({ ...expanded, [p.id]: true })} className="w-full px-4 py-3 text-left text-[14px] text-ember-text font-medium">Show all {p.models.length}</button>}
            {!p.local && <div className="px-4 py-2.5 bg-warn-tint text-[12px] leading-4 text-warn-ink">Prompts, mail and memory leave this computer.</div>}
          </div>
          {p.base_url && (
            <div className="px-1 pt-1.5 text-[12px] leading-4 text-muted">
              <span className="text-dim">Address</span> <span className="[overflow-wrap:anywhere]">{p.base_url}</span> · {addressHint(p)}
            </div>
          )}
        </Collapse>
        );
      })}

      <a href="#settings" className="text-[13.5px] leading-5 text-muted px-1 py-2.5">Add OpenAI, OpenRouter, Gemini, Claude or your own endpoint in <span className="text-ember-text font-medium">Settings → Providers</span>.</a>
    </div>
  );
}
