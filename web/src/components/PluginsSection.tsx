import { useCallback, useEffect, useState } from "react";
import { getJSON, postJSON } from "../api";
import { checkSummary, formFromServer, linkCarriesToken, serverTitle, specFromForm, statusLabel, toolLabel, type Check, type Preset, type ServerForm, type ServerRow, type SkillRow } from "../plugins";
import { Collapse } from "./Collapse";
import { Switch } from "./Switch";
import { Icon, Tile } from "./Tile";

function Chip({ status }: { status: string }) {
  const s = statusLabel(status);
  return <span className={`chip shrink-0 ${s.tone === "good" ? "chip-good" : s.tone === "warn" ? "chip-warn" : "chip-soft"}`}>{s.text}</span>;
}

function Group({ title, summary, children }: { title: string; summary?: string; children: React.ReactNode }) {
  return (
    <Collapse title={title} summary={summary}>
      <div className="glass rounded-[26px] overflow-hidden">{children}</div>
    </Collapse>
  );
}

const EMPTY: ServerForm = { name: "", title: "", target: "", description: "", env: [["", ""]] };
const field = "h-11 px-3 rounded-[14px] bg-well border border-line outline-none text-[15px]";

async function postCheck(url: string, body: unknown): Promise<Check> {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) return { ok: false, reason: typeof j.detail === "string" ? j.detail : `Failed (${r.status})` };
  return j.ok ? { ok: true, tools: j.tools || [] } : { ok: false, reason: j.reason || "It didn't answer." };
}

/** What the connection check found: the tools, and which ask for a tap. */
function CheckResult({ check }: { check: Check }) {
  if (!check.ok) return <div className="text-[13px] text-warn-ink [overflow-wrap:anywhere]">{check.reason}</div>;
  return (
    <div className="rounded-[14px] bg-well px-3 py-2.5 flex flex-col gap-1">
      <div className="text-[13px] font-semibold">{checkSummary(check.tools)}</div>
      {check.tools.length > 0 && (
        <div className="text-[12.5px] leading-[18px] text-muted [overflow-wrap:anywhere]">{check.tools.map((t) => toolLabel(t.name) + (t.asks ? " (asks)" : "")).join(" · ")}</div>
      )}
    </div>
  );
}

/** Settings: skills Odie can load and the MCP servers it connects to, from odie/skills, ~/.odie/skills
 * and ~/.odie/mcp.json. Allow code, switches, add a server, reload. */
export function PluginsSection() {
  const [skills, setSkills] = useState<SkillRow[] | null>(null);
  const [servers, setServers] = useState<ServerRow[] | null>(null);
  const [configError, setConfigError] = useState("");
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);  // name of the server being edited
  const [form, setForm] = useState<ServerForm>(EMPTY);
  const [formError, setFormError] = useState("");
  const [check, setCheck] = useState<Check | null>(null);  // the Add form's connection check
  const [presets, setPresets] = useState<Preset[]>([]);
  const [preset, setPreset] = useState<Preset | null>(null);  // Zapier or Composio, being connected
  const [link, setLink] = useState("");
  const [key, setKey] = useState("");
  const [presetCheck, setPresetCheck] = useState<Check | null>(null);

  const load = useCallback(async () => {
    try {
      const [s, m] = await Promise.all([getJSON<{ skills: SkillRow[] }>("/api/skills"), getJSON<{ servers: ServerRow[]; error: string }>("/api/mcp")]);
      setSkills(s.skills); setServers(m.servers); setConfigError(m.error || "");
    } catch { /* keep what we have */ }
  }, []);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => { getJSON<Preset[]>("/api/mcp/presets").then(setPresets).catch(() => {}); }, []);
  useEffect(() => { setCheck(null); }, [form]);  // a change needs a new check

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    try { await fn(); } catch { /* the row's status tells the story after reload */ } finally { await load(); setBusy(false); }
  }
  const del = (url: string) => fetch(url, { method: "DELETE" });

  async function addServer() {
    const r = specFromForm(form);
    if (typeof r === "string") { setFormError(r); return; }
    setFormError("");
    if (!editing && servers?.some((m) => m.name === r.name) && !confirm(`An app with the id "${r.name}" exists. Replace it?`)) return;
    await act(async () => {
      const res = await fetch("/api/mcp", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(r) });
      if (!res.ok) {
        let msg = `Couldn't save (${res.status})`;
        try { const j = await res.json(); if (typeof j.detail === "string") msg = j.detail; } catch { /* keep the status */ }
        setFormError(msg);
        return;
      }
      setAdding(false); setEditing(null); setForm(EMPTY);
    });
  }
  function openEdit(m: ServerRow) { closePreset(); setForm(formFromServer(m)); setEditing(m.name); setAdding(true); setFormError(""); }
  function closeForm() { setAdding(false); setEditing(null); setForm(EMPTY); setFormError(""); }
  async function checkForm() {
    const r = specFromForm(form);
    if (typeof r === "string") { setFormError(r); return; }
    setFormError(""); setBusy(true);
    setCheck(await postCheck("/api/mcp/check", { name: editing ?? "", spec: r.spec }));
    setBusy(false);
  }
  function openPreset(p: Preset) { closeForm(); setPreset(p); setLink(""); setKey(""); setPresetCheck(null); }
  function closePreset() { setPreset(null); setLink(""); setKey(""); setPresetCheck(null); }
  async function connectPreset(checkOnly: boolean) {
    if (!preset) return;
    setBusy(true);
    const got = await postCheck("/api/mcp/connect", { preset: preset.id, url: link.trim(), key: key.trim(), check_only: checkOnly });
    setBusy(false);
    if (checkOnly || !got.ok) { setPresetCheck(got); return; }
    closePreset();
    await load();
  }
  const editingRow = editing ? servers?.find((m) => m.name === editing) : undefined;

  return (
    <>
      <Group title="Skills" summary={skills ? `${skills.filter((x) => x.status !== "disabled" && x.status !== "error").length} on` : undefined}>
        {skills === null ? <div className="px-4 py-3.5 text-[14px] text-muted">Loading…</div>
          : skills.length === 0 ? <div className="px-4 py-3.5 text-[14px] text-muted">No skills yet.</div>
          : skills.map((s) => (
            <div key={s.name} className="flex items-start gap-3 px-4 py-3 border-b border-line last:border-b-0">
              <Tile icon={s.source === "builtin" ? "spark" : "brain"} color={s.source === "builtin" ? "violet" : "pink"} small />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap"><b className="text-[15px] font-semibold">{s.title || s.name}</b><Chip status={s.status} /></div>
                <div className="text-[13px] leading-[18px] text-muted mt-0.5 [overflow-wrap:anywhere]">{s.summary || s.description || "—"}</div>
                <div className="text-[12px] text-dim mt-0.5">{s.source === "builtin" ? "Built in" : "Yours"}{s.tools.length ? ` · ${s.tools.length} tool${s.tools.length > 1 ? "s" : ""}` : ""}</div>
                {s.reason && s.status !== "blocked" && <div className="text-[12.5px] text-warn-ink mt-1 [overflow-wrap:anywhere]">{s.reason}</div>}
                {s.status === "blocked" && (
                  <button disabled={busy} onClick={() => act(() => postJSON(`/api/skills/${s.name}/trust`, {}))} className="pill pill-solid h-9 text-[13px] shadow-none mt-2">
                    Allow code
                  </button>
                )}
              </div>
              {s.status !== "error" && (
                <Switch label={`${s.title || s.name} on`} on={s.status !== "disabled" && s.status !== "blocked"} disabled={busy || s.status === "blocked"}
                  onChange={(v) => act(() => postJSON(`/api/skills/${s.name}/enabled`, { enabled: v }))} />
              )}
            </div>
          ))}
      </Group>

      <Group title="Connected apps" summary={servers ? `${servers.filter((m) => m.enabled).length} on` : undefined}>
        {configError && <div className="px-4 py-3 text-[13px] text-warn-ink border-b border-line">{configError}</div>}
        {servers === null ? <div className="px-4 py-3.5 text-[14px] text-muted">Loading…</div>
          : servers.length === 0 && !adding ? <div className="px-4 py-3.5 text-[14px] text-muted">Nothing connected yet.</div>
          : servers.map((m) => (
            <div key={m.name} className="flex items-start gap-3 px-4 py-3 border-b border-line">
              <button type="button" onClick={() => openEdit(m)} className="flex items-start gap-3 flex-1 min-w-0 text-left" aria-label={`Edit ${serverTitle(m)}`}>
                <Tile icon={m.name === "vault" ? "note" : "globe"} color={m.name === "vault" ? "violet" : "blue"} small />
                <span className="flex-1 min-w-0">
                  <span className="flex items-center gap-2 flex-wrap"><b className="text-[15px] font-semibold">{serverTitle(m)}</b><Chip status={m.enabled ? m.status : "disabled"} /></span>
                  <span className="block text-[13px] leading-[18px] text-muted mt-0.5 [overflow-wrap:anywhere]">
                    {m.tools.length ? m.tools.map(toolLabel).join(" · ") : m.spec.description || m.spec.url || m.spec.command}
                  </span>
                  {m.readsFree && <span className="block text-[12px] text-dim mt-0.5">Reading doesn't need a tap</span>}
                  {m.reason && <span className="block text-[12.5px] text-warn-ink mt-1 [overflow-wrap:anywhere]">{m.reason}</span>}
                </span>
              </button>
              <Switch label={`${serverTitle(m)} on`} on={m.enabled} disabled={busy} onChange={(v) => act(() => postJSON(`/api/mcp/${m.name}/enabled`, { enabled: v }))} />
            </div>
          ))}
        {adding && (
          <div className="px-4 py-3.5 flex flex-col gap-2.5 border-b border-line">
            <div className="text-[14px] font-semibold">{editing ? `Edit ${form.title || form.name}` : "Connect another app (MCP)"}</div>
            <input value={form.title ?? ""} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="Name you'll see, e.g. GitHub"
              className="h-11 px-3 rounded-[14px] bg-well border border-line outline-none text-[15px]" />
            <input value={form.name} disabled={!!editing} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Short id, e.g. github" autoCapitalize="none" autoCorrect="off"
              className="h-11 px-3 rounded-[14px] bg-well border border-line outline-none text-[15px] disabled:opacity-60" />
            <input value={form.target} onChange={(e) => setForm({ ...form, target: e.target.value })} placeholder="Command (npx -y …) or URL (https://…/mcp)" autoCapitalize="none" autoCorrect="off"
              className="h-11 px-3 rounded-[14px] bg-well border border-line outline-none text-[15px]" />
            <input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder="What it's for (one line, optional)"
              className="h-11 px-3 rounded-[14px] bg-well border border-line outline-none text-[15px]" />
            <div className="text-[12.5px] text-muted">Secrets (env for a command, headers for a URL){editing ? " · •••• keeps the saved value" : ""}</div>
            {form.env.map(([k, v], i) => (
              <div key={i} className="flex gap-2">
                <input value={k} onChange={(e) => setForm({ ...form, env: form.env.map((r, j) => (j === i ? [e.target.value, r[1]] : r)) })} placeholder="KEY" autoCapitalize="none"
                  className="flex-1 min-w-0 h-10 px-3 rounded-[12px] bg-well border border-line outline-none text-[14px]" />
                <input value={v} type="password" onChange={(e) => setForm({ ...form, env: form.env.map((r, j) => (j === i ? [r[0], e.target.value] : r)) })} placeholder="value"
                  className="flex-1 min-w-0 h-10 px-3 rounded-[12px] bg-well border border-line outline-none text-[14px]" />
              </div>
            ))}
            <button type="button" onClick={() => setForm({ ...form, env: [...form.env, ["", ""]] })} className="self-start text-[13px] text-ember-text font-semibold">+ Another secret</button>
            {editingRow && (
              <div className="flex items-start gap-3 py-1">
                <div className="flex-1 min-w-0">
                  <div className="text-[14px] font-medium">Reading doesn't need a tap</div>
                  <div className="text-[12.5px] leading-[18px] text-muted">Only tools that find, get, list, search or fetch. Sending, creating, changing and deleting always ask.</div>
                </div>
                <Switch label="Reading doesn't need a tap" on={editingRow.readsFree} disabled={busy}
                  onChange={(v) => act(() => postJSON(`/api/mcp/${editingRow.name}/reads_free`, { on: v }))} />
              </div>
            )}
            {check && <CheckResult check={check} />}
            {formError && <div className="text-[13px] text-warn-ink">{formError}</div>}
            <div className="flex gap-2 flex-wrap">
              <button disabled={busy} onClick={checkForm} className="pill h-10 text-[14px] shadow-none">{busy && !check ? "Checking…" : "Check"}</button>
              <button disabled={busy} onClick={addServer} className="pill pill-solid h-10 text-[14px] shadow-none">{check && !check.ok ? "Save anyway" : editing ? "Save" : "Connect"}</button>
              <button onClick={closeForm} className="pill h-10 text-[14px] shadow-none">Cancel</button>
              {editing && (
                <button disabled={busy} onClick={() => { if (confirm(`Remove ${form.title || form.name}?`)) void act(async () => { await del(`/api/mcp/${editing}`); closeForm(); }); }}
                  className="ml-auto text-[13.5px] font-semibold text-warn-ink">Remove</button>
              )}
            </div>
          </div>
        )}
        {preset && (
          <div className="px-4 py-3.5 flex flex-col gap-2.5 border-b border-line">
            <div className="text-[14px] font-semibold">Connect {preset.title}</div>
            <div className="text-[12.5px] leading-[18px] text-muted">{preset.where} Your data then goes through {preset.title}.</div>
            {servers?.some((m) => serverTitle(m) === preset.title) && (
              <div className="text-[12.5px] leading-[18px] text-warn-ink">This replaces your {preset.title} connection: the new link and code take the old ones' place, and its switches stay.</div>
            )}
            <input value={link} type="text" autoComplete="off" autoCapitalize="none" autoCorrect="off" spellCheck={false} onChange={(e) => { setLink(e.target.value); setPresetCheck(null); }} placeholder={`The ${preset.title} server link (https://…)`}
              aria-label={`${preset.title} server link`} className={field} />
            {linkCarriesToken(link) && <div className="text-[12.5px] leading-[18px] text-muted">This link has its code in it, so leave the code box empty.</div>}
            <input value={key} type="password" autoComplete="off" onChange={(e) => { setKey(e.target.value); setPresetCheck(null); }} placeholder={preset.key_label}
              aria-label={preset.key_label} className={field} />
            {presetCheck && <CheckResult check={presetCheck} />}
            <div className="flex gap-2 flex-wrap">
              <button disabled={busy || !link.trim()} onClick={() => connectPreset(true)} className="pill h-10 text-[14px] shadow-none">{busy && !presetCheck ? "Checking…" : "Check"}</button>
              <button disabled={busy || !presetCheck?.ok} onClick={() => connectPreset(false)} className="pill pill-solid h-10 text-[14px] shadow-none">Connect</button>
              <button onClick={closePreset} className="pill h-10 text-[14px] shadow-none">Cancel</button>
            </div>
            <div className="text-[12px] leading-4 text-muted">The link and key stay on this computer, in a file only you can read.</div>
          </div>
        )}
        {!adding && !preset && (
          <div className="px-4 pt-3 text-[12.5px] leading-[18px] text-muted">
            Connect your mail, calendar and other apps. Zapier and Composio link many apps in one go; any other MCP server works too.
          </div>
        )}
        <div className="px-4 py-3 flex gap-2 flex-wrap">
          {!adding && !preset && presets.map((p) => (
            <button key={p.id} onClick={() => openPreset(p)} className="pill pill-flat h-10 text-[14px]">{p.title}</button>
          ))}
          {!adding && !preset && <button onClick={() => { setForm(EMPTY); setEditing(null); setAdding(true); }} className="pill pill-flat h-10 text-[14px]">Another app</button>}
          <button disabled={busy} onClick={() => act(() => postJSON("/api/plugins/reload", {}))} aria-label="Reload skills and apps" title="Reload skills and apps" className="pill pill-flat w-10 h-10 px-0 ml-auto">
            <span className={`flex ${busy ? "animate-spin" : ""}`}><Icon name="refresh" size={15} /></span>
          </button>
        </div>
      </Group>
    </>
  );
}
