import { useCallback, useEffect, useRef, useState } from "react";
import { getJSON, postJSON } from "../api";
import { said, tone, type BrainReport } from "../brain";
import { usePersona } from "../persona";
import { Avatar } from "../components/Avatar";
import { Orb } from "../components/Orb";
import { needsPasscode, type PairStatus } from "../devices";
import { checkSummary, linkCarriesToken } from "../plugins";
import { BY_HAND, LABEL, STEPS, brainDone, chipState, firstPick, formFor, keyRoute, modelRows, visibleThread, type AppCard, type Card, type KeyCard, type Panel, type Phone, type SetupState, type Turn } from "../setup";

type Models = { providers: { id: string; name: string; local: boolean; error: string | null; models: { id: string; local: boolean }[] }[] };
const CLOUD = [
  { id: "openrouter", name: "OpenRouter", company: "OpenRouter and the model's maker" },
  { id: "gemini", name: "Gemini", company: "Google" },
  { id: "openai", name: "OpenAI", company: "OpenAI" },
  { id: "anthropic", name: "Claude", company: "Anthropic" },
];

async function putKey(url: string, apiKey: string): Promise<string | null> {
  const r = await fetch(url, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ api_key: apiKey }) });
  if (r.ok) return null;
  return (await r.json().catch(() => ({}))).detail || "That key didn't work.";
}

function Checklist({ s }: { s: SetupState }) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex gap-1.5 overflow-x-auto no-scrollbar -mx-1 px-1" aria-label="Setup steps">
        {STEPS.map((step) => {
          const st = chipState(step, s);
          const style = st === "done" ? "bg-moss-tint text-moss-text" : st === "skipped" ? "bg-well text-dim line-through" : st === "current" ? "glass-solid text-ink font-semibold" : "bg-well text-muted";
          return <span key={step} className={`shrink-0 h-8 px-3 rounded-full grid place-items-center text-[12.5px] ${style}`}>{st === "done" ? "✓ " : ""}{LABEL[step]}</span>;
        })}
      </div>
      {s.current && BY_HAND[s.current] && (
        <a href={BY_HAND[s.current]} className="text-[13px] text-muted self-start py-2.5">Do it in Settings instead</a>
      )}
    </div>
  );
}

function BrainStep({ onDone }: { onDone: () => void }) {
  const [data, setData] = useState<Models | null>(null);
  const [reports, setReports] = useState<Record<string, BrainReport>>({});
  const [checking, setChecking] = useState<string | null>(null);
  const [cloud, setCloud] = useState(CLOUD[0].id);
  const [key, setKey] = useState("");
  const [keyError, setKeyError] = useState("");
  const [query, setQuery] = useState("");
  const load = useCallback(() => { getJSON<Models>("/api/models").then(setData).catch(() => {}); }, []);
  useEffect(load, [load]);

  async function check(provider: string, model: string) {
    setChecking(`${provider}/${model}`);
    try {
      const rep = await postJSON<BrainReport>("/api/brain/check", { provider, model });
      setReports((r) => ({ ...r, [`${provider}/${model}`]: rep }));
    }
    finally { setChecking(null); }
  }
  async function use(provider: string, model: string) {
    await fetch("/api/models/selection", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ slot: "chat", provider, model }) });
    await postJSON("/api/setup/brain", {});
    onDone();
  }
  async function saveKey() {
    setKeyError("");
    const problem = await putKey(`/api/providers/${cloud}/key`, key.trim());
    if (problem) { setKeyError(problem); return; }
    setKey("");
    load();
  }
  const rows = modelRows(data?.providers ?? [], query, 8);
  const anyGood = Object.values(reports).some((r) => r && brainDone(r));
  const company = CLOUD.find((c) => c.id === cloud)!.company;
  return (
    <div className="flex flex-col gap-4">
      <div className="text-[15px] leading-[22px] text-ink-2">First, a brain. Pick a model and I'll check it can do the job: about 30 seconds.</div>
      <div className="flex gap-2">
        <input value={query} onChange={(e) => setQuery(e.target.value)} type="search" aria-label="Find a model" placeholder="Find a model, e.g. gemma, glm, claude"
          autoCapitalize="none" autoCorrect="off" className="flex-1 min-w-0 h-11 px-4 rounded-full bg-well border border-line outline-none text-[15px] focus:border-line-2" />
        <button onClick={load} className="h-11 px-4 rounded-full border border-line-2 text-[13.5px] font-medium shrink-0">Look again</button>
      </div>
      <div className="glass rounded-[26px] overflow-hidden">
        {!data && <div className="px-4 py-3 text-[14px] text-muted">Looking for models…</div>}
        {data && rows.length === 0 && <div className="px-4 py-3 text-[14px] text-muted">No models found on this computer. Use a cloud key below, or start LM Studio or Ollama and come back.</div>}
        {rows.map(({ p, m }, i) => {
          const id = `${p.id}/${m.id}`;
          const r = reports[id];
          return (
            <div key={id} className={`px-4 py-3 flex flex-col gap-1.5 ${i < rows.length - 1 ? "border-b border-line" : ""}`}>
              <div className="flex items-center gap-2">
                <span className="flex-1 min-w-0 text-[15px] truncate">{m.id}</span>
                <span className="text-[12px] text-muted shrink-0">{p.name}{m.local ? " · on this computer" : " · cloud"}</span>
              </div>
              {r && <div role="status" className={`text-[13px] ${tone(r) === "good" ? "text-moss-text" : tone(r) === "bad" ? "text-ember-text" : "text-warn-ink"}`}>{said(r)}</div>}
              <div className="flex gap-2">
                <button onClick={() => check(p.id, m.id)} disabled={checking !== null} className="h-9 px-3.5 rounded-full border border-line-2 text-[13.5px] font-medium flex items-center gap-2">
                  {checking === id ? <><span className="spinner" /> Checking…</> : r ? "Check again" : "Check"}
                </button>
                {(brainDone(r) || (r && !anyGood)) && <button onClick={() => use(p.id, m.id)} className="h-9 px-3.5 rounded-full bg-ember text-on-ember text-[13.5px] font-semibold">{brainDone(r) ? "Use this" : "Use it anyway"}</button>}
              </div>
            </div>
          );
        })}
      </div>
      <form onSubmit={(e) => { e.preventDefault(); if (key.trim()) saveKey(); }} className="glass rounded-[26px] p-4 flex flex-col gap-2.5">
        <div className="text-[14px] font-semibold">Or use a cloud model with a key</div>
        <div className="flex gap-1.5 flex-wrap">
          {CLOUD.map((c) => <button type="button" key={c.id} onClick={() => setCloud(c.id)} className={`h-10 px-3.5 rounded-full text-[13.5px] ${cloud === c.id ? "glass-solid font-semibold" : "bg-well text-muted"}`}>{c.name}</button>)}
        </div>
        <input type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} placeholder={`${CLOUD.find((c) => c.id === cloud)!.name} key`}
          className="h-11 px-4 rounded-full bg-well border border-line outline-none text-[15px] focus:border-line-2" />
        <div className="text-[12px] leading-4 text-warn-ink">Your chats, notes and memory will go to {company}.</div>
        {keyError && <div className="text-[13px] text-ember-text">{keyError}</div>}
        <button type="submit" disabled={!key.trim()} className="self-end h-10 px-5 rounded-full bg-ember text-on-ember text-[14px] font-semibold whitespace-nowrap disabled:opacity-50">Save key</button>
        <a href="https://lmstudio.ai" target="_blank" rel="noreferrer" className="text-[12.5px] leading-[18px] text-muted">Want everything to stay on this computer? Set up a local model ↗</a>
      </form>
    </div>
  );
}

function KeyCardView({ card, onSaved }: { card: KeyCard; onSaved: (provider: string) => void }) {
  const [key, setKey] = useState("");
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  async function save() {
    setError("");
    const problem = await putKey(keyRoute(card), key.trim());
    if (problem) { setError(problem); return; }
    setSaved(true);
    setKey("");
    onSaved(card.provider);
  }
  if (saved) return <div className="text-[13px] text-moss-text">✓ {card.label} key saved</div>;
  return (
    <form onSubmit={(e) => { e.preventDefault(); if (key.trim()) save(); }} className="glass rounded-[22px] p-3.5 flex flex-col gap-2">
      <div className="text-[14px] font-semibold">{card.label} key</div>
      <input type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} placeholder="Paste the key here"
        className="h-11 px-4 rounded-full bg-well border border-line outline-none text-[15px] focus:border-line-2" />
      <div className="text-[12px] leading-4 text-muted">{card.note} It's checked, then saved on this computer; I never see it.</div>
      {error && <div className="text-[13px] text-ember-text">{error}</div>}
      <button type="submit" disabled={!key.trim()} className="self-end h-9 px-4 rounded-full bg-ember text-on-ember text-[13.5px] font-semibold disabled:opacity-50">Check and save</button>
    </form>
  );
}

/** Zapier's or Composio's link (and key) go straight to /api/mcp/connect, which checks them first; the assistant never
 * sees them. */
function AppCardView({ card, onSaved }: { card: AppCard; onSaved: (app: string) => void }) {
  const [url, setUrl] = useState("");
  const [key, setKey] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState("");
  async function save() {
    setBusy(true);
    setError("");
    const r = await fetch("/api/mcp/connect", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ preset: card.app, url: url.trim(), key: key.trim() }) });
    const j = await r.json().catch(() => ({}));
    setBusy(false);
    if (!r.ok) { setError(typeof j.detail === "string" ? j.detail : "That link didn't work."); return; }
    setSaved(checkSummary(j.tools || []));
    setUrl(""); setKey("");
    onSaved(card.app);
  }
  if (saved) return <div className="text-[13px] text-moss-text">✓ {card.label} connected · {saved}</div>;
  const field = "h-11 px-4 rounded-full bg-well border border-line outline-none text-[15px] focus:border-line-2";
  return (
    <form onSubmit={(e) => { e.preventDefault(); if (url.trim() && !busy) save(); }} className="glass rounded-[22px] p-3.5 flex flex-col gap-2">
      <div className="text-[14px] font-semibold">Connect {card.label}</div>
      {card.steps?.length
        ? <ol className="list-decimal pl-5 flex flex-col gap-1 text-[13px] leading-[19px] text-ink-2">{card.steps.map((t) => <li key={t}>{t}</li>)}</ol>
        : <div className="text-[12.5px] leading-[18px] text-muted">{card.where}</div>}
      <input type="text" autoComplete="off" autoCapitalize="none" autoCorrect="off" spellCheck={false} value={url} onChange={(e) => setUrl(e.target.value)} placeholder={`Paste the ${card.label} server link`} aria-label={`${card.label} server link`} className={field} />
      {linkCarriesToken(url) && <div className="text-[12.5px] leading-[18px] text-muted">This link has its code in it, so leave the code box empty.</div>}
      <input type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} placeholder={card.key_label} aria-label={card.key_label} className={field} />
      <div className="text-[12px] leading-4 text-muted">It's checked, then saved on this computer; I never see it. Your data then goes through {card.label}.</div>
      {error && <div className="text-[13px] text-ember-text [overflow-wrap:anywhere]">{error}</div>}
      <button type="submit" disabled={!url.trim() || busy} className="self-end h-9 px-4 rounded-full bg-ember text-on-ember text-[13.5px] font-semibold disabled:opacity-50">{busy ? "Checking…" : "Check and connect"}</button>
    </form>
  );
}

/** The phone step: is Tailscale here and passing the phone to Odie? Then the address, the steps, and a pairing code
 * (a QR code the phone's camera opens, valid once for 10 minutes). */
export function PhoneBlock({ phone, onCheck }: { phone: Phone; onCheck: () => void }) {
  const [made, setMade] = useState<{ code: string; svg: string; url: string } | null>(null);
  const [error, setError] = useState("");
  async function code() {
    setError("");
    try { setMade(await postJSON<{ code: string; svg: string; url: string }>("/api/devices/code", {})); }
    catch { setError("I couldn't make a pairing code. Try again, or use Settings → Devices."); }
  }
  if (!phone.tailscale) return (
    <div className="flex flex-col gap-2 text-[14px] leading-[20px]">
      <div>Tailscale isn't on this computer yet.</div>
      <ol className="list-decimal pl-5 flex flex-col gap-1 text-ink-2">
        <li>Get it at <a href={phone.download} target="_blank" rel="noreferrer" className="text-ember-text font-medium underline">{phone.download.replace("https://", "")}</a> and sign in.</li>
        <li>Come back here and press Check again.</li>
      </ol>
      <button onClick={onCheck} className="self-start h-9 px-4 rounded-full border border-line-2 text-[13.5px] font-medium">Check again</button>
    </div>
  );
  if (!phone.serving) return (
    <div className="flex flex-col gap-2 text-[14px] leading-[20px]">
      <div>Tailscale is here, but it doesn't pass your phone to me yet. In Terminal, run:</div>
      <code className="font-mono text-[13.5px] rounded-[10px] bg-well px-3 py-2 select-all">{phone.serve_command}</code>
      <div className="text-muted text-[13px]">Then press Check again. If it still doesn't show: run <code className="font-mono">odie restart</code> in Terminal, refresh this page, and press Check again.</div>
      <button onClick={onCheck} className="self-start h-9 px-4 rounded-full border border-line-2 text-[13.5px] font-medium">Check again</button>
    </div>
  );
  return (
    <div className="flex flex-col gap-3 text-[14px] leading-[20px]">
      <div>On your phone, I'm at <a href={phone.address} target="_blank" rel="noreferrer" className="text-ember-text font-medium underline break-all">{phone.address}</a></div>
      <ol className="list-decimal pl-5 flex flex-col gap-1 text-ink-2">{phone.steps.map((t) => <li key={t}>{t}</li>)}</ol>
      {phone.pairing && (made ? (
        <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-center">
          <div className="w-[200px] rounded-[14px] overflow-hidden bg-white p-2 [&_svg]:w-full [&_svg]:h-auto" aria-label="QR code for pairing" dangerouslySetInnerHTML={{ __html: made.svg }} />
          <div className="flex flex-col gap-1">
            <div className="font-mono text-[24px] tracking-[0.18em] font-semibold" aria-label="Pairing code">{made.code}</div>
            <div className="text-[12.5px] text-muted max-w-[300px]">Valid once, for 10 minutes. Scan it with the phone's camera, or open the address on the phone and type the code.</div>
            <button onClick={code} className="self-start text-[13px] text-ember-text font-medium">Make a new code</button>
          </div>
        </div>
      ) : (
        <button onClick={code} className="self-start h-10 px-4 rounded-full glass-solid font-semibold">Show the pairing code</button>
      ))}
      {error && <div className="text-[13px] text-warn-ink">{error}</div>}
    </div>
  );
}

/** The current step's controls: its choices as radio buttons (each with what it needs first: a key form, an app form, a
 * folder), Continue and Skip. What's chosen here is saved by code, not by the model. */
export function StepPanel({ panel, onChoose, onCheck, busy }: { panel: Panel; onChoose: (choice: string, value?: unknown) => Promise<string>; onCheck: () => void; busy: boolean }) {
  const [pick, setPick] = useState(firstPick(panel));
  const [fields, setFields] = useState<Record<string, string>>(Object.fromEntries(panel.fields.map((f) => [f.id, f.value])));
  const [path, setPath] = useState("");
  const [error, setError] = useState("");
  // A new step, or the same step with other choices (Check again found Tailscale): start from its recommended choice.
  const shape = `${panel.step}:${panel.choices.map((c) => c.id).join(",")}`;
  useEffect(() => { setPick(firstPick(panel)); setFields(Object.fromEntries(panel.fields.map((f) => [f.id, f.value]))); setError(""); }, [shape]);  // eslint-disable-line react-hooks/exhaustive-deps
  const choice = panel.choices.find((c) => c.id === pick);
  const form = formFor(choice);
  async function go(id: string, value?: unknown) { setError(await onChoose(id, value)); }
  const field = "h-11 px-4 rounded-full bg-well border border-line outline-none text-[15px] focus:border-line-2";
  const canContinue = panel.step === "names" ? !!fields.user_name?.trim() : form === "path" ? !!path.trim() : !!choice && (form === null);
  return (
    <section aria-label={`${panel.label} step`} className="glass rounded-[26px] p-4 flex flex-col gap-3">
      {panel.explain && <div className="text-[13.5px] leading-[20px] text-muted">{panel.explain}</div>}
      {panel.fields.length > 0 && (
        <div className="grid sm:grid-cols-2 gap-2.5">
          {panel.fields.map((f) => (
            <label key={f.id} className="flex flex-col gap-1 text-[13px] text-muted">{f.label}
              <input value={fields[f.id] ?? ""} onChange={(e) => setFields({ ...fields, [f.id]: e.target.value })} className={field} />
            </label>
          ))}
        </div>
      )}
      {panel.phone && <PhoneBlock phone={panel.phone} onCheck={onCheck} />}
      {panel.choices.length > 1 && (
        <div role="radiogroup" aria-label={panel.label} className="flex flex-col gap-1.5">
          {panel.choices.map((c) => (
            <div key={c.id} className="flex flex-col gap-2">
              <label className={`flex items-start gap-3 px-3.5 py-2.5 rounded-[16px] border cursor-pointer ${pick === c.id ? "border-ember bg-well" : "border-line"}`}>
                <input type="radio" name={`choice-${panel.step}`} checked={pick === c.id} onChange={() => { setPick(c.id); setError(""); }} className="mt-1 accent-[var(--t-action)]" />
                <span className="flex flex-col min-w-0">
                  <span className="text-[15px] font-medium">{c.label}{c.recommended && <span className="ml-2 text-[11.5px] font-semibold text-moss-text">Recommended</span>}</span>
                  {c.note && <span className="text-[12.5px] leading-[18px] text-muted break-words">{c.note}</span>}
                </span>
              </label>
              {/* What the picked choice needs first, right under it */}
              {pick === c.id && form === "key" && <div className="pl-7"><KeyCardView key={`${panel.step}-${c.id}`} card={c.needs as KeyCard} onSaved={() => void go(c.id)} /></div>}
              {pick === c.id && form === "app" && <div className="pl-7"><AppCardView key={`${panel.step}-${c.id}`} card={c.needs as AppCard} onSaved={() => void go(c.id)} /></div>}
              {pick === c.id && form === "path" && <input value={path} onChange={(e) => setPath(e.target.value)} placeholder="/Users/you/Documents/Notes" aria-label="The folder's full path" className={`${field} ml-7`} />}
            </div>
          ))}
        </div>
      )}
      {error && <div role="alert" className="text-[13px] text-ember-text">{error}</div>}
      <div className="flex flex-wrap gap-2 justify-end">
        {panel.skip && <button disabled={busy} onClick={() => void go("skip")} className="h-10 px-4 rounded-full border border-line-2 text-[14px] font-medium disabled:opacity-50">{panel.skip}</button>}
        {(form === null || form === "path") && panel.choices.length > 0 && (
          <button disabled={busy || !canContinue} onClick={() => void go(pick, panel.step === "names" ? fields : form === "path" ? path.trim() : undefined)}
            className="h-10 px-5 rounded-full bg-ember text-on-ember font-semibold disabled:opacity-50">{panel.choices.length === 1 && panel.step !== "names" ? choice?.label : "Continue"}</button>
        )}
      </div>
    </section>
  );
}

function Conversation({ s, setS }: { s: SetupState; setS: (s: SetupState) => void }) {
  const persona = usePersona();
  const [cards, setCards] = useState<Card[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const end = useRef<HTMLDivElement>(null);
  const [panel, setPanel] = useState<Panel | null>(s.panel ?? null);
  const take = useCallback((t: Turn) => { setS(t.state); setCards((c) => [...c, ...t.cards]); if (t.panel !== undefined) setPanel(t.panel); }, [setS]);
  useEffect(() => {
    if (s.thread.length === 0 && !busy) {
      setBusy(true);
      postJSON<Turn>("/api/setup/event", { kind: "start", provider: "" }).then(take).catch(() => {}).finally(() => setBusy(false));
    }
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [s.thread.length, busy, cards.length, panel?.step]);
  async function choose(choice: string, value?: unknown): Promise<string> {
    if (!panel) return "";  // not dropped while busy: a key saved during an answer still moves the step on
    setBusy(true);
    try {
      const t = await postJSON<Turn>("/api/setup/choose", { step: panel.step, choice, value: value ?? null });
      if (t.error) { setPanel(t.panel ?? panel); return t.error; }
      setCards([]);
      take(t);
      return "";
    } catch { return "That didn't go through. Try again."; }
    finally { setBusy(false); }
  }
  async function check() { setPanel((await getJSON<SetupState>("/api/setup")).panel ?? null); }
  async function send() {
    const t = text.trim();
    if (!t || busy) return;
    setText("");
    setBusy(true);
    setError("");
    setS({ ...s, thread: [...s.thread, { role: "user", text: t }] });
    try { take(await postJSON<Turn>("/api/setup/chat", { text: t })); }
    catch { setError("That didn't go through. Try again."); }
    finally { setBusy(false); }
  }
  async function saved(kind: "key_saved" | "app_saved", provider: string) {
    setBusy(true);
    setError("");
    try { take(await postJSON<Turn>("/api/setup/event", { kind, provider })); }
    catch { setError("It's saved, but I couldn't carry on. Say anything to continue."); }
    finally { setBusy(false); }
  }
  const visible = visibleThread(s.thread);
  return (
    <div className="flex flex-col gap-3">
      {visible.map((m, i) => m.role === "user" ? (
        <div key={i} className="ml-auto max-w-[80%] bubble-me rounded-[24px] rounded-br-[8px] px-4 py-3 text-[15.5px] leading-[1.5] whitespace-pre-wrap break-words">{m.text}</div>
      ) : (
        <div key={i} className="flex gap-2 items-start">
          <Avatar size={32} />
          <div className="glass rounded-[8px_26px_26px_26px] px-4 py-3 text-[15px] leading-[1.5] whitespace-pre-wrap">{m.text}</div>
        </div>
      ))}
      {cards.map((c, i) => c.type === "app"
        ? <AppCardView key={`${c.app}-${i}`} card={c} onSaved={(app) => saved("app_saved", app)} />
        : <KeyCardView key={`${c.provider}-${i}`} card={c} onSaved={(provider) => saved("key_saved", provider)} />)}
      {busy && <div role="status" className="flex items-center gap-3"><Orb state="thinking" size={26} /><span className="text-[14px] font-semibold shimmer-text">{persona.name} is thinking</span></div>}
      {error && <div role="alert" className="text-[13px] text-ember-text">{error}</div>}
      {!s.done && panel && <StepPanel panel={panel} onChoose={choose} onCheck={() => void check()} busy={busy} />}
      <div ref={end} className="scroll-mb-28" />
      {!s.done && (
        <div className="flex gap-2 sticky bottom-0 py-3 bg-ground border-t border-line">
          <input value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") send(); }} placeholder="Or type an answer or a question" aria-label="Your answer"
            className="flex-1 h-12 px-4 rounded-full glass-solid outline-none text-[15.5px]" />
          <button onClick={send} disabled={busy || !text.trim()} className="h-12 px-5 rounded-full bg-ember text-on-ember font-semibold disabled:opacity-50">Send</button>
        </div>
      )}
    </div>
  );
}

/** The recovery passcode, offered when setup ends while pairing is on and none exists: four words that let a new
 * device in when no paired one is at hand. Shown once. */
function PasscodeOffer() {
  const [status, setStatus] = useState<PairStatus | null>(null);
  const [words, setWords] = useState("");
  const [error, setError] = useState("");
  useEffect(() => { getJSON<PairStatus>("/api/pair/status").then(setStatus).catch(() => {}); }, []);
  async function make() {
    setError("");
    try { setWords((await postJSON<{ passcode: string }>("/api/devices/passcode", {})).passcode); }
    catch { setError("That didn't work. You can make one later in Settings → Devices."); }
  }
  if (!words && !needsPasscode(status)) return null;
  return (
    <div className="flex flex-col gap-2 w-full">
      <div className="text-[14px] leading-[20px] text-muted">One last thing: a recovery passcode. Four words that pair a new device if you lose this one.</div>
      {words ? (
        <>
          <div className="font-mono text-[18px] font-semibold rounded-[12px] bg-well px-3 py-2.5 select-all">{words}</div>
          <div className="text-[12.5px] leading-[18px] text-muted">Write it down somewhere safe. It isn't shown again.</div>
        </>
      ) : (
        <button onClick={make} className="h-10 px-4 rounded-full glass-solid font-semibold self-start">Make my recovery passcode</button>
      )}
      {error && <div className="text-[13px] text-warn-ink">{error}</div>}
    </div>
  );
}

export function Setup() {
  const persona = usePersona();
  const [s, setS] = useState<SetupState | null>(null);
  const load = useCallback(() => { getJSON<SetupState>("/api/setup").then(setS).catch(() => {}); }, []);
  useEffect(load, [load]);
  if (!s) return <div className="h-full grid place-items-center"><Orb state="thinking" size={40} /></div>;
  return (
    <div className="h-full overflow-y-auto px-[18px] sm:px-8 safe-top flex flex-col gap-5 pb-6">
      <div className="flex items-center gap-3 pt-2">
        <div className="text-[21px] font-bold tracking-[-0.015em] flex-1">Setting up {persona.name}</div>
        {s.can_leave && (
          <button onClick={async () => { await postJSON("/api/setup/leave", {}); location.hash = "#chat"; location.reload(); }}
            className="h-9 px-4 rounded-full border border-line-2 text-[13.5px] font-medium">Leave setup</button>
        )}
      </div>
      {s.can_leave && <div className="text-[13px] text-muted -mt-3">Everything that's set stays as it is. Change only what you want, or leave.</div>}
      <Checklist s={s} />
      {s.steps.brain === "todo" ? <BrainStep onDone={load} /> : <Conversation s={s} setS={setS} />}
      {s.done && (
        <div className="glass rounded-[26px] p-4 flex flex-col gap-2 items-start">
          <div className="text-[15px] font-semibold">All set.</div>
          <PasscodeOffer />
          <button onClick={() => { location.hash = "#chat"; location.reload(); }} className="h-10 px-4 rounded-full bg-ember text-on-ember font-semibold">Start chatting</button>
        </div>
      )}
    </div>
  );
}
