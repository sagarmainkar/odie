import { AnimatePresence, motion } from "framer-motion";
import { pushSub } from "../push";
import { brainState } from "../brain";
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { deleteJSON, getJSON, postJSON, putJSON, urlBase64ToUint8Array } from "../api";
import { applyLook, getLook, type Look } from "../theme";
import { Icon, Tile, type IconName, type TileColor } from "../components/Tile";
import { Avatar } from "../components/Avatar";
import { PluginsSection } from "../components/PluginsSection";
import { googleRows, renewBy, type GoogleCheck } from "../google";
import { ProvidersSection } from "../components/ProvidersSection";
import { SearchSection } from "../components/SearchSection";
import { Switch } from "../components/Switch";
import { DevicesSection } from "../components/DevicesSection";
import { UpdateSection } from "../components/UpdateSection";
import { BrowserSection } from "../components/BrowserSection";
import { personaChanged, usePersona } from "../persona";
import { profileChanged, useProfile } from "../profile";
import { has, useCaps } from "../capabilities";
import { notesRow, type VaultInfo } from "../vault";
import { photosRow, type PhotosInfo } from "../photos";
import { engineLine, voiceGroups, voiceSection } from "../voiceSettings";
import { afterTurnOn, sendPosition, type LocationInfo } from "../location";
import { LocationRowView } from "../components/LocationRow";
import { LABEL, type Panel, type Step, type Turn } from "../setup";
import { PhoneBlock, StepPanel } from "./Setup";
import { MacAppsBlock } from "../components/MacAppsBlock";
import type { MacApps } from "../mac";

type Health = { status: string; version?: string; model: string; provider?: string; leaves_mini?: boolean; lm_studio: boolean; connections: { gmail: boolean; vault: boolean }; brain_chosen?: boolean; brain_reachable?: boolean };
type Google = { client_configured: boolean; connected: boolean; email?: string; redirect_uri: string; setup: string; account: string; services?: { gmail: boolean; calendar: boolean } | null; connected_at?: string | null };
type Dot = boolean | "warn" | "loading";

function StatusDot({ ok }: { ok: Dot }) {
  const c = ok === "loading" ? "bg-dim ring-surface-2" : ok === "warn" ? "bg-gold ring-gold-tint" : ok ? "bg-moss ring-moss-tint" : "bg-ember ring-ember-tint";
  return <span className={`w-2 h-2 rounded-full ring-2 shrink-0 ${c}`} />;
}

function Chevron() {
  return <svg className="text-dim shrink-0" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M9 6l6 6-6 6" /></svg>;
}

function Row({ ok, title, sub, meta, right, chevron, icon }: { ok?: Dot; title: string; sub?: ReactNode; meta?: ReactNode; right?: ReactNode; chevron?: boolean; icon?: { icon: IconName; color: TileColor } }) {
  return (
    <div className="flex items-center gap-3 px-4 py-3 min-h-14 border-b border-line last:border-b-0">
      {icon ? (
        // The tile says what it is; a small dot on its corner says how it's doing.
        <span className="relative shrink-0"><Tile icon={icon.icon} color={icon.color} small />{ok !== undefined && <span className="absolute -right-0.5 -bottom-0.5 rounded-full bg-[var(--t-surface-2)] p-[2px] flex"><StatusDot ok={ok} /></span>}</span>
      ) : ok !== undefined && <StatusDot ok={ok} />}
      <div className="flex-1 min-w-0">
        <div className="text-[15px] leading-5 font-medium">{title}</div>
        {sub && <div className="text-[13px] leading-[18px] text-muted truncate">{sub}</div>}
        {meta && <div className="text-[12px] leading-4 text-dim mt-0.5">{meta}</div>}
      </div>
      {right && <div className="text-[13px] text-muted shrink-0">{right}</div>}
      {chevron && <Chevron />}
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <div className="text-[13px] leading-5 font-bold text-muted px-1.5">{title}</div>
      <div className="glass rounded-[26px] overflow-hidden">{children}</div>
    </section>
  );
}

function Pill({ tone, children }: { tone: "moss" | "ember" | "gold"; children: ReactNode }) {
  const c = tone === "moss" ? "chip-good" : tone === "ember" ? "chip-warn" : "chip-warn";
  return <span className={`chip shrink-0 ${c}`}>{children}</span>;
}

function GoogleRows({ g, flash, setupAction, reload }: { g: Google | null; flash: string; setupAction: ReactNode; reload: () => void }) {
  const [check, setCheck] = useState<GoogleCheck | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (g?.connected) getJSON<GoogleCheck>("/api/google/check").then(setCheck).catch(() => setCheck({ gmail: "error", calendar: "error" })); }, [g?.connected]);
  const rows = googleRows(check, !!g?.connected);
  const dot = (state: string) => (state === "Connected" ? true : state === "Checking…" ? "loading" : "warn") as Dot;
  async function disconnect() {
    if (!confirm("Disconnect Google? Odie stops reading mail and the calendar until you connect again.")) return;
    setBusy(true);
    try { await postJSON("/api/google/disconnect", {}); } finally { setBusy(false); setCheck(null); reload(); }
  }
  if (!g) return <div className="border-b border-line"><Row icon={{ icon: "mail", color: "blue" }} ok="loading" title="Google" sub="…" /></div>;
  return (
    <div className="border-b border-line">
      <Row icon={{ icon: "mail", color: "blue" }} ok={g.connected ? dot(rows.gmail) : false} title="Gmail" sub={g.connected ? `${g.email ?? ""} · ${rows.gmail}` : "Not connected"} />
      <Row icon={{ icon: "cal", color: "orange" }} ok={g.connected ? dot(rows.calendar) : false} title="Calendar" sub={rows.calendar} />
      <div className="px-4 pb-3 flex flex-col gap-1.5">
        {flash && <div className="text-[13px] text-moss-text">{flash}</div>}
        {setupAction}
        {g.client_configured && (
          <div className="flex items-center gap-2 flex-wrap">
            {rows.action && <a href="/api/google/connect" className="h-10 px-4 rounded-[14px] bg-ember text-on-ember font-semibold text-[14px] flex items-center">{rows.action}</a>}
            {!rows.action && g.connected && <a href="/api/google/connect" className="h-10 flex items-center text-ember-text font-medium text-[14px]">Reconnect</a>}
            {g.connected && <button disabled={busy} onClick={() => void disconnect()} className="ml-auto h-10 text-[13.5px] font-semibold text-warn-ink">Disconnect</button>}
          </div>
        )}
        {g.connected && renewBy(g.connected_at) && <div className="text-[12px] text-dim">{renewBy(g.connected_at)}</div>}
      </div>
    </div>
  );
}


function AssistantSection() {
  const persona = usePersona();
  const [draft, setDraft] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
    const profile = useProfile();
    const [you, setYou] = useState<string | null>(null);
    const yourName = you ?? profile?.user_name ?? "";
    async function saveYou() {
      const r = await fetch("/api/profile", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ user_name: yourName }) });
      if (r.ok) { setYou(null); profileChanged(); setNote(`Saved. ${persona.name} will call you ${yourName || "nothing in particular"}.`); setTimeout(() => setNote(""), 3000); }
    }
    const name = draft ?? persona.name;
  async function saveName() {
    const r = await fetch("/api/persona", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }) });
    if (r.ok) { setDraft(null); personaChanged(); setNote("Saved. She'll use the new name from your next message."); setTimeout(() => setNote(""), 3000); }
  }
  async function upload(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0]; e.target.value = "";
    if (!f) return;
    setBusy(true);
    try {
      const fd = new FormData(); fd.append("file", f);
      const r = await fetch("/api/persona/avatar", { method: "POST", body: fd });
      setNote(r.ok ? "Photo updated." : "That photo didn't work. Try a JPEG or PNG.");
      personaChanged();
    } finally { setBusy(false); setTimeout(() => setNote(""), 3000); }
  }
  async function removePhoto() { await fetch("/api/persona/avatar", { method: "DELETE" }); personaChanged(); }
  return (
    <section className="glass rounded-[26px] px-4 pt-6 pb-4 flex flex-col items-center text-center gap-1">
      <button onClick={() => fileRef.current?.click()} aria-label="Change photo" className="relative">
        <Avatar size={96} />
        {busy && <span className="absolute inset-0 flex items-center justify-center"><span className="spinner" /></span>}
      </button>
      <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={upload} />
      <label className="sr-only" htmlFor="persona-name">Name</label>
      <div className="flex items-center gap-2 mt-3 w-full max-w-[280px]">
        <input id="persona-name" value={name} maxLength={24} onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") void saveName(); }}
          className="flex-1 min-w-0 h-11 px-3 rounded-[14px] bg-transparent text-center text-[26px] font-bold tracking-[-0.02em] outline-none focus:bg-well" />
        {draft !== null && draft !== persona.name && <button onClick={() => void saveName()} className="pill pill-solid h-10 text-[14px] shadow-none">Save</button>}
      </div>
        <div className="text-[14px] text-muted">Your assistant · lives on this {profile?.machine ?? "computer"}</div>
        <div className="flex items-center gap-2 mt-3 w-full max-w-[280px]">
          <label htmlFor="your-name" className="text-[13px] text-muted shrink-0">Calls you</label>
          <input id="your-name" value={yourName} maxLength={40} placeholder="Your name" onChange={(e) => setYou(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") void saveYou(); }}
            className="flex-1 min-w-0 h-10 px-3 rounded-[14px] bg-well text-[15px] outline-none" />
          {you !== null && you !== (profile?.user_name ?? "") && <button onClick={() => void saveYou()} className="pill pill-solid h-9 text-[13.5px] shadow-none">Save</button>}
        </div>
        <div className="flex items-center justify-center gap-2 mt-3 flex-wrap">
        <button onClick={() => fileRef.current?.click()} className="pill pill-flat h-10 text-[13.5px]">{persona.avatar_url ? "Change photo" : "Use a photo"}</button>
        {persona.avatar_url && <button onClick={() => void removePhoto()} className="pill pill-flat h-10 text-[13.5px]">Use the orb</button>}
      </div>
      <AnimatePresence>{note && <motion.span initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="text-[13px] text-good mt-1">{note}</motion.span>}</AnimatePresence>
    </section>
  );
}

type VoiceInfo = import("../voiceSettings").VoiceInfo;  // the shape /api/voice answers (voiceSettings.ts)

/** The phone, after setup: the same block as the setup step (is Tailscale here, does it pass the phone to Odie, the
 *  address and the pairing code), so a skipped phone can be set up from here. Check again asks the server to look. */
function PhoneSection() {
  const [panel, setPanel] = useState<Panel | null>(null);
  const load = () => getJSON<Panel>("/api/setup/panel/phone").then(setPanel).catch(() => {});
  useEffect(() => { void load(); }, []);
  if (!panel?.phone) return null;
  return (
    <Section title="Phone">
      <div className="p-4 flex flex-col gap-3">
        {panel.explain && <div className="text-[13px] leading-[18px] text-muted">{panel.explain}</div>}
        <PhoneBlock phone={panel.phone} onCheck={() => void load()} />
      </div>
    </Section>
  );
}

function VoiceSection() {
  const [v, setV] = useState<VoiceInfo | null>(null);
  const [playing, setPlaying] = useState<string | null>(null);
  const audio = useRef<HTMLAudioElement | null>(null);
  const load = () => getJSON<VoiceInfo>("/api/voice").then(setV).catch(() => {});
  useEffect(() => { load(); return () => audio.current?.pause(); }, []);
  function play(engine: string, id: string) {
    audio.current?.pause();
    const key = `${engine}/${id}`;
    if (playing === key) { setPlaying(null); return; }
    const a = new Audio(`/api/voice/preview/${engine}/${id}`);
    audio.current = a; setPlaying(key);
    a.onended = () => setPlaying(null); a.onerror = () => setPlaying(null);
    void a.play().catch(() => setPlaying(null));
  }
  async function save(body: { engine?: string; voice?: string; reminders_spoken?: boolean }) {
    const r = await fetch("/api/voice", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (r.ok) { const j = await r.json(); setV((x) => (x ? { ...x, engine: j.engine, voice: j.voice, reminders_spoken: j.reminders_spoken } : x)); }
  }
  if (!v) return null;
  const shown = voiceSection(v);  // no engine at all: one plain line, and nothing below reads an engine that isn't there
  // Odie's own voice needs Apple Silicon; on an Intel Mac the server offers no local engine and says so here.
  const noLocal = v.local_voice === false;
  const about = (
    <div className="text-[13px] leading-[18px] text-muted px-1">
      Read-aloud (the speaker under each reply).{" "}
      {noLocal && <>Odie's own voice (Kokoro) needs Apple Silicon, so it isn't offered on this Mac.{" "}</>}
      {v.engines.some((e) => e.id === "openai") ? <>With your OpenAI key: its voices, and dictation that writes as you speak.</> : <>Add an OpenAI key in Providers for OpenAI voices and live dictation.</>}
    </div>
  );
  if (!shown.picker) {
    // No engine at all (the voice worker off, no OpenAI key): the phone's own voice still reads replies.
    return (
      <Section title="Voice">
        <div className="p-3 flex flex-col gap-3">
          {about}
          <div className="text-[13px] leading-[18px] text-muted px-1">{shown.note} Until then, replies are read with the browser's own voice.</div>
        </div>
      </Section>
    );
  }
  const eng = shown.engine;
  const line = engineLine(eng);  // on this computer or not, and what to do when it can't speak (Phonon: ollama pull)
  return (
    <Section title="Voice">
      <div className="p-3 flex flex-col gap-3">
        {about}
        <div className="bg-well rounded-[14px] p-1 flex gap-1" role="radiogroup" aria-label="Read-aloud engine">
          {v.engines.map((e) => (
            <button key={e.id} role="radio" aria-checked={e.id === v.engine} disabled={!e.available} onClick={() => void save({ engine: e.id })}
              className={`relative flex-1 h-11 rounded-[10px] text-[14px] font-medium disabled:opacity-40 ${e.id === v.engine ? "text-ink" : "text-muted"}`}>
              {e.id === v.engine && <motion.span layoutId="engine-seg" transition={{ duration: 0.2 }} className="absolute inset-0 rounded-[10px] bg-surface" style={{ boxShadow: "var(--t-shadow-card)" }} />}
              <span className="relative">{e.label}</span>
            </button>
          ))}
        </div>
        <div className="text-[13px] leading-[18px] px-1 flex items-start gap-2">
          {line.pill && <Pill tone={line.pill === "on this computer" ? "moss" : "ember"}>{line.pill}</Pill>}
          <span className="text-muted">{line.text}</span>
        </div>
        {voiceGroups(eng).map((g) => {
          const list = g.voices;
          return (
            <div key={g.key}>
              {g.title && <div className="px-1 pb-1.5 text-[13px] font-semibold text-muted">{g.title}</div>}
              <div className="grid grid-cols-2 gap-2">
                {list.map((x) => {
                  const on = x.id === v.voice;
                  const key = `${eng.id}/${x.id}`;
                  return (
                    <div key={x.id} className={`flex items-center gap-1 rounded-[14px] border pl-3 pr-1 min-h-12 ${on ? "border-ember-text bg-ember-tint" : "border-line"}`}>
                      <button onClick={() => { void save({ voice: x.id }); play(eng.id, x.id); }} className="flex-1 text-left py-1.5 min-w-0">
                        <span className={`block text-[15px] leading-5 ${on ? "font-semibold text-ember-text" : ""}`}>{x.label}</span>
                        {x.note && <span className="block text-[12px] leading-4 text-dim truncate">{x.note}</span>}
                      </button>
                      <button onClick={() => play(eng.id, x.id)} aria-label={`Hear ${x.label}`} className="w-10 h-10 rounded-full flex items-center justify-center text-muted shrink-0">
                        {playing === key ? <span className="spinner" /> : <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z" /></svg>}
                      </button>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
        {eng.id === "maya1" && <div className="text-[12px] leading-4 text-dim px-1">The first preview loads Maya1 (about half a minute). Replies are read with laughs, sighs and other expressions where they fit.</div>}
        <div className="flex items-start gap-3 pt-1">
          <div className="flex-1 min-w-0">
            <div className="text-[14.5px] font-medium">Speak reminders</div>
            <div className="text-[12.5px] leading-[18px] text-muted">{eng.available
              ? "Each reminder also arrives as a voice message in this voice, and plays if Odie is open."
              : "Needs a voice that's ready: this one isn't available right now."}</div>
          </div>
          <Switch label="Speak reminders" on={!!v.reminders_spoken} disabled={!eng.available && !v.reminders_spoken}
            onChange={(on) => void save({ reminders_spoken: on })} />
        </div>
      </div>
    </Section>
  );
}

/** Where long-term memory really is: the file, and whether it's in the vault (so Obsidian shows it). */
function MemoryRow() {
  const [v, setV] = useState<VaultInfo | null>(null);
  useEffect(() => { getJSON<VaultInfo>("/api/vault").then(setV).catch(() => {}); }, []);
  const file = v?.memory_file ?? "";
  const dir = v?.settings.dir ?? "";
  const inVault = !!dir && file.startsWith(dir);
  const home = file.replace(/^\/Users\/[^/]+/, "~");
  return <Row icon={{ icon: "brain", color: "violet" }} ok={true} title="Long-term memory" sub="Reviewed every 10 turns"
    meta={<span className="font-mono [overflow-wrap:anywhere]">{inVault ? file.slice(dir.length).replace(/^\//, "") : home}</span>}
    right={inVault ? <Pill tone="moss">Obsidian</Pill> : undefined} />;
}

function skippedList(steps: Step[]): string {
  return steps.map((st) => LABEL[st].toLowerCase()).join(", ");
}

function NotesRow() {
  const [v, setV] = useState<VaultInfo | null>(null);
  const [panel, setPanel] = useState<Panel | null>(null);  // the vault, then search by meaning: setup's own choices
  const [busy, setBusy] = useState(false);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = () => getJSON<VaultInfo>("/api/vault").then((x) => {
      if (!live) return;
      setV(x);
      if (x.progress.running) timer = setTimeout(load, 2000);  // counts up while a pass runs
    }).catch(() => {});
    load();
    return () => { live = false; clearTimeout(timer); };
  }, [tick]);
  async function open(step: "vault" | "embeddings") {
    const p = await getJSON<Panel>(`/api/setup/panel/${step}`);
    setPanel({ ...p, skip: step === "embeddings" ? "Not now: find notes by their words" : null });
  }
  async function choose(choice: string, value?: unknown): Promise<string> {
    if (!panel) return "";
    if (choice === "skip") { setPanel(null); return ""; }
    setBusy(true);
    try {
      const t = await postJSON<Turn>("/api/setup/choose", { step: panel.step, choice, value: value ?? null });
      if (t.error) return t.error;
      if (panel.step === "vault") await open("embeddings"); else setPanel(null);
      setTick((n) => n + 1);
      return "";
    } catch { return "That didn't go through. Try again."; }
    finally { setBusy(false); }
  }
  const row = v ? notesRow(v) : null;
  const button = (label: string) => <button onClick={() => (panel ? setPanel(null) : void open("vault"))} className="h-10 px-2 -mx-2 text-ember-text font-medium">{panel ? "Close" : label}</button>;
  return (
    <>
      {row
        ? <Row icon={{ icon: "note", color: "blue" }} ok={row.state === "ok" ? true : row.state === "warn" ? "warn" : "loading"} title="Notes"
            sub={row.sub} meta={<span className="font-mono [overflow-wrap:anywhere]">{row.meta}</span>} right={button("Change")} />
        : v && <Row icon={{ icon: "note", color: "blue" }} ok="warn" title="Notes" sub="Not set up: pick or make an Obsidian vault" right={button("Set up")} />}
      {panel && <div className="px-3 py-3 border-b border-line"><div className="text-[14px] font-medium px-1 pb-2">{panel.question}</div>
        <StepPanel panel={panel} onChoose={choose} onCheck={() => void open(panel.step as "vault" | "embeddings")} busy={busy} /></div>}
    </>
  );
}

/** The user's Photos library in the index: off until they say yes (here or in setup); on, what it knows and the
 * screenshots choice. The library is read in the background; the row counts up while that runs. */
function PhotosRow() {
  const [v, setV] = useState<PhotosInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = () => getJSON<PhotosInfo>("/api/photos").then((x) => {
      if (!live) return;
      setV(x);
      if (x.progress.running || (x.settings.on && !x.status?.photos_at)) timer = setTimeout(load, 2000);  // counts up while the library is read
    }).catch(() => {});
    load();
    return () => { live = false; clearTimeout(timer); };
  }, [tick]);
  async function change(body: { on?: boolean; screenshots?: boolean }) {
    setBusy(true);
    try { setV(await putJSON<PhotosInfo>("/api/photos", body)); setTick((n) => n + 1); } catch { /* the row keeps what it showed */ }
    finally { setBusy(false); }
  }
  if (!v) return null;
  const row = photosRow(v);
  const link = "h-10 px-2 -mx-2 text-ember-text font-medium disabled:opacity-50";
  const right = v.settings.on
    ? <span className="flex items-center gap-3 shrink-0">
        <button disabled={busy} onClick={() => void change({ screenshots: !v.settings.screenshots })} className={link}>{v.settings.screenshots ? "No screenshots" : "Screenshots too"}</button>
        <button disabled={busy} onClick={() => void change({ on: false })} className={link}>Off</button>
      </span>
    : <button disabled={busy} onClick={() => void change({ on: true })} className={link}>Turn on</button>;
  const ok: Dot = row.state === "ok" ? true : row.state === "warn" ? "warn" : row.state === "busy" ? "loading" : false;
  return <Row icon={{ icon: "photo", color: "orange" }} ok={ok} title="Photos" sub={row.sub} right={right} />;
}

/** Settings' Location row (components/LocationRow.tsx draws it): loads the setting, and turns the taps into calls. */
function LocationRow() {
  const [v, setV] = useState<{ info: LocationInfo; now: Date } | null>(null);
  const [busy, setBusy] = useState(false);
  const show = (info: LocationInfo) => setV({ info, now: new Date() });  // the clock is read when the answer lands, not on each draw
  useEffect(() => {
    let live = true;
    getJSON<LocationInfo>("/api/location").then((x) => { if (live) show(x); }).catch(() => {});
    return () => { live = false; };
  }, []);
  async function change(go: () => Promise<LocationInfo>) {
    setBusy(true);
    try { show(await go()); } catch { /* the row keeps what it showed */ }
    finally { setBusy(false); }
  }
  async function turnOn() {
    setBusy(true);
    try {
      const answered = await putJSON<LocationInfo>("/api/location", { on: true });
      show(answered);
      if (afterTurnOn(answered) === "fix") {
        const fixed = await sendPosition();  // the browser asks its own question if it hasn't yet; a refusal or a timeout changes nothing
        if (fixed) show(fixed);
      }
    } catch { /* the row keeps what it showed */ }
    finally { setBusy(false); }
  }
  if (!v) return null;
  return <LocationRowView info={v.info} now={v.now} busy={busy} Row={Row} onTurnOn={() => void turnOn()}
    onOff={() => void change(() => putJSON<LocationInfo>("/api/location", { on: false }))}
    onForget={() => void change(() => deleteJSON<LocationInfo>("/api/location"))} />;
}

function isApple(): boolean {
  const touchMac = navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1;  // an iPad asks for the desktop site
  return /iPhone|iPad|iPod/.test(navigator.userAgent) || touchMac;
}

/** Settings' Brain row, in words: the model and where it runs, or why there's none.
 *    ready        -> "deepseek-v4.1-flash:cloud · ollama"
 *    unreachable  -> "gemma-4-26b · LM Studio isn't reachable"
 *    none         -> "No brain yet: choose one"
 *    not loaded   -> "…" */
function brainSub(h: Health | null): string {
  if (!h) return "…";
  const where = h.provider === "lmstudio" || !h.provider ? "LM Studio" : h.provider;
  const state = brainState(h.brain_chosen, h.brain_reachable);
  if (state === "none") return "No brain yet: choose one";
  if (state === "unreachable") return `${h.model.split("/").pop()} · ${where} isn't reachable`;
  return `${h.model.split("/").pop()} · ${where}`;
}

/** The Brain row's dot: amber when the brain leaves the computer, isn't reachable or isn't chosen; green otherwise. */
function brainOk(h: Health | null): Dot {
  if (!h) return "loading";
  if (brainState(h.brain_chosen, h.brain_reachable) !== "ready" || h.leaves_mini) return "warn";
  return true;
}

export function Settings() {
  const caps = useCaps();
  const [h, setH] = useState<Health | null>(null);
  const [g, setG] = useState<Google | null>(null);
  const [push, setPush] = useState<string>(typeof Notification !== "undefined" ? Notification.permission : "unsupported");
  const [subscribed, setSubscribed] = useState(false);
  const [tested, setTested] = useState("");
  const [showSetup, setShowSetup] = useState(false);
  const [skipped, setSkipped] = useState<Step[]>([]);  // setup's skipped steps: what "setup again" will do
  useEffect(() => { getJSON<{ skipped?: Step[] }>("/api/setup").then((x) => setSkipped(x.skipped ?? [])).catch(() => {}); }, []);
  const [look, setLook] = useState<Look>(getLook());
  const [soul, setSoul] = useState<{ text: string; custom: boolean; path?: string } | null>(null);
  const [soulDraft, setSoulDraft] = useState("");
  const [soulOpen, setSoulOpen] = useState(false);
  const [soulSaved, setSoulSaved] = useState("");
  const flash = location.hash.includes("google=connected") ? "Connected. Gmail and Calendar are ready." : location.hash.includes("google=error") ? "Google said no. Try again." : "";
  const [macApps, setMacApps] = useState<MacApps | null>(null);
  const pushSupported = typeof Notification !== "undefined" && "serviceWorker" in navigator && "PushManager" in window;
  const standalone = typeof window !== "undefined" && (window.matchMedia("(display-mode: standalone)").matches || (navigator as any).standalone === true);

  useEffect(() => {
    getJSON<Health>("/api/health").then(setH).catch(() => {});
    getJSON<MacApps>("/api/mac/apps").then(setMacApps).catch(() => {});
    getJSON<Google>("/api/google/status").then(setG).catch(() => {});
    getJSON<{ text: string; custom: boolean; path: string }>("/api/soul").then((x) => { setSoul(x); setSoulDraft(x.text); }).catch(() => {});
    if (pushSupported) navigator.serviceWorker.ready.then((r) => r.pushManager.getSubscription()).then((s) => setSubscribed(!!s)).catch(() => {});
  }, [pushSupported]);

  function pickLook(l: Look) { setLook(l); applyLook(l); }
  async function saveSoul(text: string) {
    const r = await fetch("/api/soul", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
    const j = await r.json();
    setSoul((s) => ({ text: text || (s?.text ?? ""), custom: j.custom, path: s?.path }));
    setSoulSaved(j.custom ? "Saved. Odie uses it from the next message." : "Back to the default personality.");
    setTimeout(() => setSoulSaved(""), 3000);
  }
  async function enablePush() {
    if (!pushSupported) {
      setPush(standalone ? "This browser can't do web push." : "Add Odie to your Home Screen (Share > Add to Home Screen), open it from the icon, then tap again.");
      return;
    }
    try {
      const perm = await Notification.requestPermission();
      setPush(perm);
      if (perm !== "granted") return;
      const reg = await navigator.serviceWorker.ready;
      const { publicKey } = await getJSON<{ publicKey: string }>("/api/push/public-key");
      const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlBase64ToUint8Array(publicKey) as BufferSource });
      await postJSON("/api/push/subscribe", sub.toJSON());
      setSubscribed(true);
    } catch (e) { console.warn("push subscribe failed", e); setPush("failed"); }
  }
  async function testPush() {
    try { const r = await postJSON<{ sent: number }>("/api/push/test", {}); setTested(r.sent ? "Sent. Check your lock screen." : "No device subscribed."); }
    catch { setTested("Couldn't send."); }
    setTimeout(() => setTested(""), 3000);
  }

  const googleAction = !g ? null : !g.client_configured ? (
    <div className="flex flex-col gap-2">
      <button onClick={() => setShowSetup((v) => !v)} className="self-start h-11 px-4 rounded-[14px] border border-line-2 text-[14px] font-medium">One-time setup on the mini</button>
      {showSetup && <div className="text-[13px] leading-[18px] text-muted break-words">{g.setup}</div>}
    </div>
  ) : !g.connected ? (
    <a href="/api/google/connect" className="self-start h-11 px-4 rounded-[14px] bg-ember text-on-ember font-semibold text-[15px] flex items-center">Connect Google</a>
  ) : g.services && !g.services.calendar ? (
    <a href="/api/google/connect" className="self-start h-11 px-4 rounded-[14px] bg-ember text-on-ember font-semibold text-[15px] flex items-center">Add Calendar</a>
  ) : null;

  return (
    <div className="h-full overflow-y-auto no-scrollbar px-[18px] lg:px-8 safe-top flex flex-col gap-6 pb-6">
      <div className="flex items-center gap-3">
        {/* A desktop has the rail for going back to Today (hidden! with "!": .pill sets its own display, which would win). */}
        <a href="#today" aria-label="Back to Today" className="pill w-11 px-0 lg:hidden!"><Icon name="back" /></a>
        <div className="text-[21px] font-bold tracking-[-0.015em]">Settings</div>
      </div>

      {/* A desktop shows two columns: who the assistant is and what it connects to on the left, the rest on the right.
          On a phone and a tablet the wrappers vanish (display: contents): one column, in the same order as always. */}
      <div className="contents lg:grid lg:grid-cols-2 lg:gap-6 lg:items-start">
        <div className="contents lg:flex lg:flex-col lg:gap-6 lg:min-w-0">
          <AssistantSection />

          <Section title="Connections">
            {has(caps, "google") && <GoogleRows g={g} flash={flash} setupAction={g && !g.client_configured ? googleAction : null} reload={() => getJSON<Google>("/api/google/status").then(setG).catch(() => {})} />}
            <a href="#brain" className="block active:bg-well">
              <Row icon={{ icon: "brain", color: "ink" }} ok={brainOk(h)} title="Brain" sub={brainSub(h)}
                right={h && brainState(h.brain_chosen, h.brain_reachable) === "ready" ? (h.leaves_mini ? <Pill tone="ember">leaves this computer</Pill> : <Pill tone="moss">on this computer</Pill>) : undefined} chevron />
            </a>
          </Section>

          <DevicesSection />

          <ProvidersSection />

          <SearchSection />
        </div>
        <div className="contents lg:flex lg:flex-col lg:gap-6 lg:min-w-0">
          {has(caps, "browser") && <BrowserSection />}

          <PluginsSection />
          <a href="#sample" className="-mt-3 px-1.5 py-2.5 self-start text-[13px] text-ember-text font-medium">See a sample chat →</a>

          {macApps?.mac && (
            <Section title="Mac apps">
              <MacAppsBlock data={macApps} onChange={setMacApps} />
            </Section>
          )}

          <Section title="Look">
            <div className="p-1 m-3 mb-2 rounded-full bg-well flex gap-1" role="radiogroup" aria-label="Look">
              {([["auto", "Auto"], ["light", "Light"], ["dark", "Dark"]] as const).map(([k, l]) => (
                <button key={k} role="radio" aria-checked={look === k} onClick={() => pickLook(k)}
                  className={`flex-1 h-9 rounded-full text-[13px] font-semibold transition-colors ${look === k ? "glass-solid text-ink shadow-[0_4px_12px_-6px_rgba(0,0,0,.25)]" : "text-muted"}`}>{l}</button>
              ))}
            </div>
            <div className="px-4 pb-3 text-[12.5px] text-muted">Auto follows your phone: dark in dark mode; in light mode the colour follows the time of day, warm in the morning, sky at noon, rose in the evening.</div>
          </Section>

          <VoiceSection />

          <Section title="Personality">
            <button onClick={() => setSoulOpen((v) => !v)} className="w-full text-left active:bg-well" aria-expanded={soulOpen}>
              <Row icon={{ icon: "spark", color: "pink" }} ok={soul ? true : "loading"} title="How Odie talks" sub={soul?.custom ? "Your own words in use" : "The default personality"} chevron />
            </button>
            <AnimatePresence initial={false}>
              {soulOpen && (
                <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.2 }} className="overflow-hidden">
                  <div className="px-4 pb-4 pt-1 flex flex-col gap-2.5">
                    <textarea value={soulDraft} onChange={(e) => setSoulDraft(e.target.value)} rows={7} spellCheck={false}
                      className="w-full bg-well border border-line rounded-[12px] p-3 text-[14px] leading-[22px] outline-none focus:border-line-2" />
                    <div className="flex gap-2 items-center">
                      <button onClick={() => saveSoul(soulDraft)} className="h-11 px-4 rounded-[14px] bg-ember text-on-ember font-semibold text-[15px]">Save</button>
                      <button onClick={() => saveSoul("")} className="h-11 px-4 rounded-[14px] border border-line-2 text-[15px]">Reset</button>
                      <AnimatePresence>{soulSaved && <motion.span initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="text-[13px] text-moss-text">{soulSaved}</motion.span>}</AnimatePresence>
                    </div>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </Section>

          <Section title="Memory">
            <NotesRow />
            <PhotosRow />
            <LocationRow />
            <MemoryRow />
          </Section>

          {has(caps, "update") && <UpdateSection version={h?.version} />}

          <PhoneSection />

          <Section title="Setup">
            <button onClick={async () => {
              const what = skipped.length ? `Set up what was skipped (${skippedList(skipped)})?` : "Go through every step again?";
              if (!confirm(`${what} Everything that's set stays as it is until you change it, and you can leave setup at any time.`)) return;
              await postJSON("/api/setup/restart", {}); location.hash = "#setup"; location.reload();
            }} className="block w-full text-left active:bg-well">
              <Row icon={{ icon: "spark", color: "violet" }} ok={skipped.length ? "warn" : true} title={skipped.length ? "Finish setup" : "Run setup again"}
                sub={skipped.length ? `Skipped: ${skippedList(skipped)}` : "Names, notes, search, voice, apps and phone, one at a time"} chevron />
            </button>
          </Section>

          <Section title="Notifications">
            {!pushSupported ? (
              <Row ok="warn" icon={{ icon: "bell", color: "green" }} title="Push to this device" sub={standalone ? "Not available in this browser" : "Add to Home Screen, then open Odie from the icon"} />
            ) : subscribed ? (
              <Row ok={true} icon={{ icon: "bell", color: "green" }} title="Push to this device" sub={tested || "Reminders and briefs reach this phone"}
                right={<button onClick={testPush} className="h-11 px-1 text-ember-text font-medium text-[14px]">Send a test</button>} />
            ) : (
              <>
                <Row ok="warn" icon={{ icon: "bell", color: "green" }} title="Push to this device" sub={pushSub(push, isApple())} />
                {push !== "denied" && (
                  <div className="px-4 pb-3"><button onClick={enablePush} className="h-11 px-4 rounded-[14px] bg-ember text-on-ember font-semibold text-[15px]">Enable notifications</button></div>
                )}
              </>
            )}
          </Section>
        </div>
      </div>

      <div className="text-[12px] text-dim text-center">Odie{h?.version ? ` ${h.version}` : ""} · runs on this computer</div>
    </div>
  );
}
