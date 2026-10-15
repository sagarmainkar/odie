import { AnimatePresence, motion } from "framer-motion";
import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import ReactMarkdown from "react-markdown";
import { userLocale } from "../locale";
import { getJSON } from "../api";
import { canTurnOn, offConfirm, sinceText, type SavedLogin, type SignIn, type Site } from "../signin";
import { LiveView } from "./LiveView";
import { Switch } from "./Switch";
import { Tile } from "./Tile";

async function call(url: string, method: string, body?: unknown): Promise<{ ok: boolean; data: any }> {
  const r = await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
  return { ok: r.ok, data: await r.json().catch(() => ({})) };
}

/** Settings → Browser: signed-in browsing (odie/signin), off until the user reads what it risks and ticks the box;
 * then the sites Odie is signed in to, signing in ahead of time, signing out, and the UPI ID for collect requests. */
export function BrowserSection() {
  const [info, setInfo] = useState<SignIn | null>(null);
  const [list, setList] = useState<Site[]>([]);
  const [sheet, setSheet] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [upi, setUpi] = useState("");
  const [live, setLive] = useState<{ tab: string; start: string } | null>(null);
  const [logins, setLogins] = useState<SavedLogin[]>([]);
  const [adding, setAdding] = useState<{ site: string; username: string; password: string } | null>(null);

  const load = useCallback(() => {
    void call("/api/browser/signin", "GET").then((r) => {
      if (!r.ok) return;
      const s = r.data as SignIn;
      setInfo(s); setUpi(s.upi_id ?? "");
      if (s.on) {
        void call("/api/browser/sites", "GET").then((x) => setList(x.ok ? x.data.sites ?? [] : []));
        void getJSON<{ logins: SavedLogin[] }>("/api/browser/logins").then((x) => setLogins(x.logins)).catch(() => setLogins([]));
      } else { setList([]); setLogins([]); }
    });
  }, []);
  useEffect(() => { load(); }, [load]);

  async function run(fn: () => Promise<{ ok: boolean; data: any } | null>) {
    setBusy(true); setError("");
    const r = await fn();
    setBusy(false);
    if (r && !r.ok) setError(r.data.detail || "That didn't work. Try again.");
    else if (r?.data?.warning) setError(r.data.warning);
    load();
    return r;
  }
  const turnOff = () => void run(async () => {
    if (!confirm(offConfirm(logins.length))) return null;
    return call("/api/browser/signin/off", "POST");
  });
  const signOut = (d: string) => void run(async () => {
    if (!confirm(`Sign out of ${d}? Odie forgets that session${logins.some((l) => l.site === d) ? " and its saved login" : ""}.`)) return null;
    return call(`/api/browser/sites/${encodeURIComponent(d)}/signout`, "POST");
  });
  const signOutAll = () => void run(async () => {
    if (!confirm(`Sign out of every site in Odie's browser?${logins.length ? " Odie also forgets every saved login." : ""}`)) return null;
    return call("/api/browser/signout", "POST");
  });
  const saveUpi = () => void run(() => call("/api/browser/upi", "PUT", { upi_id: upi }));
  const deleteLogin = (site: string) => void run(async () => {
    if (!confirm(`Forget the saved login for ${site}?`)) return null;
    return call(`/api/browser/logins/${encodeURIComponent(site)}`, "DELETE");
  });
  const forgetLogins = () => void run(async () => {
    if (!confirm("Forget every saved login? They're removed from this Mac's Keychain.")) return null;
    return call("/api/browser/logins/forget", "POST");
  });
  const saveLogin = () => void run(async () => {
    if (!adding) return null;
    const r = await call("/api/browser/logins", "POST", adding);
    if (r.ok) setAdding(null);
    return r;
  });
  const signInTo = () => {
    const where = prompt("Sign in to which site? For example amazon.in");
    if (where?.trim()) setLive({ tab: `signin-${Math.random().toString(36).slice(2, 10)}`, start: where.trim() });
  };

  if (!info) return null;
  const since = sinceText(info.accepted_at, userLocale());
  return (
    <section className="flex flex-col gap-2">
      <div className="text-[13px] leading-5 font-bold text-muted px-1.5">Browser</div>
      <div className="glass rounded-[26px] overflow-hidden">
        <div className="flex items-center gap-3 px-4 py-3 min-h-14 border-b border-line">
          <Tile icon="lock" color={info.on ? "green" : "ink"} small />
          <div className="flex-1 min-w-0">
            <div className="text-[15px] leading-5 font-medium">Signed-in browsing <span className="chip chip-warn ml-1 align-middle">Experimental</span></div>
            <div className="text-[13px] leading-[18px] text-muted">{info.on ? `On since ${since}, risks accepted` : "Off. Sign in to sites in Odie's browser so it can use your accounts."}</div>
          </div>
          <Switch on={info.on} disabled={busy} label="Signed-in browsing" onChange={(v) => (v ? setSheet(true) : turnOff())} />
        </div>
        {info.terms_changed && (
          <div className="px-4 py-3 border-b border-line flex flex-col gap-2 bg-warn-tint">
            <div className="text-[13px] leading-[19px] text-ink-2">What signed-in browsing risks has changed since you turned it on, so it's off until you read it again.</div>
            <button onClick={() => setSheet(true)} className="pill h-10 text-[14px] shadow-none self-start">Read it again</button>
          </div>
        )}
        {info.on && (
          <>
            {list.map((s) => (
              <div key={s.domain} className="flex items-center gap-3 px-4 py-3 min-h-14 border-b border-line">
                <Tile icon="globe" color="blue" small />
                <div className="flex-1 min-w-0">
                  <div className="text-[15px] leading-5 font-medium truncate">{s.domain}</div>
                  <div className="text-[13px] leading-[18px] text-muted">Signed in since {sinceText(s.since, userLocale())}</div>
                </div>
                <button disabled={busy} onClick={() => signOut(s.domain)} className="text-[13.5px] font-semibold text-warn-ink shrink-0 h-11 px-1">Sign out</button>
              </div>
            ))}
            <button disabled={busy} onClick={signInTo} className="w-full flex items-center gap-3 px-4 py-3 min-h-14 border-b border-line text-left active:bg-well">
              <Tile icon="plus" color="blue" small />
              <span className="flex-1 text-[15px] font-medium">Sign in to a site…</span>
            </button>
            {list.length > 0 && (
              <button disabled={busy} onClick={signOutAll} className="w-full flex items-center gap-3 px-4 py-3 min-h-14 border-b border-line text-left active:bg-well">
                <Tile icon="x" color="ink" small />
                <span className="flex-1 text-[15px] font-medium text-warn-ink">Sign out of everything</span>
              </button>
            )}
            <div className="px-4 pt-3 pb-1 text-[13px] font-semibold text-muted">Saved logins</div>
            {logins.map((l) => (
              <div key={l.site} className="flex items-center gap-3 px-4 py-3 min-h-14 border-b border-line">
                <Tile icon="lock" color="green" small />
                <div className="flex-1 min-w-0">
                  <div className="text-[15px] leading-5 font-medium truncate">{l.site}</div>
                  <div className="text-[13px] leading-[18px] text-muted truncate">{l.username} · {l.last_used ? `used ${sinceText(l.last_used, userLocale())}` : `saved ${sinceText(l.saved_at, userLocale())}`}</div>
                </div>
                <button disabled={busy} onClick={() => deleteLogin(l.site)} className="text-[13.5px] font-semibold text-warn-ink shrink-0 h-11 px-1">Delete</button>
              </div>
            ))}
            {adding ? (
              <form className="px-4 py-3 flex flex-col gap-2 border-b border-line" onSubmit={(e) => { e.preventDefault(); saveLogin(); }}>
                <input value={adding.site} onChange={(e) => setAdding({ ...adding, site: e.target.value })} placeholder="Site (amazon.in)" aria-label="Site"
                  autoCapitalize="off" autoCorrect="off" spellCheck={false} className="h-11 rounded-full bg-well px-4 text-[16px] outline-none" />
                <input value={adding.username} onChange={(e) => setAdding({ ...adding, username: e.target.value })} placeholder="Email or phone" aria-label="Username"
                  autoComplete="username" autoCapitalize="off" autoCorrect="off" spellCheck={false} className="h-11 rounded-full bg-well px-4 text-[16px] outline-none" />
                <input value={adding.password} onChange={(e) => setAdding({ ...adding, password: e.target.value })} placeholder="Password" aria-label="Password"
                  type="password" autoComplete="current-password" className="h-11 rounded-full bg-well px-4 text-[16px] outline-none" />
                <div className="flex gap-2">
                  <button disabled={busy || !adding.site.trim() || !adding.username.trim() || !adding.password} className="pill pill-solid h-10 text-[14px] shadow-none disabled:opacity-40">Save</button>
                  <button type="button" onClick={() => setAdding(null)} className="pill h-10 text-[14px] shadow-none">Cancel</button>
                </div>
                <div className="text-[12.5px] leading-[18px] text-muted">Kept in this Mac's Keychain. Odie's browser signs in with it by itself; the AI never sees it.</div>
              </form>
            ) : (
              <button disabled={busy} onClick={() => setAdding({ site: "", username: "", password: "" })} className="w-full flex items-center gap-3 px-4 py-3 min-h-14 border-b border-line text-left active:bg-well">
                <Tile icon="plus" color="green" small />
                <span className="flex-1 text-[15px] font-medium">Add a login</span>
              </button>
            )}
            {logins.length > 0 && (
              <button disabled={busy} onClick={forgetLogins} className="w-full flex items-center gap-3 px-4 py-3 min-h-14 border-b border-line text-left active:bg-well">
                <Tile icon="x" color="ink" small />
                <span className="flex-1 text-[15px] font-medium text-warn-ink">Forget every saved login</span>
              </button>
            )}
            <form className="px-4 py-3 flex flex-col gap-2 border-b border-line" onSubmit={(e) => { e.preventDefault(); saveUpi(); }}>
              <label htmlFor="upi-id" className="text-[15px] leading-5 font-medium">UPI ID for payments</label>
              <div className="flex gap-2">
                <input id="upi-id" value={upi} onChange={(e) => setUpi(e.target.value)} placeholder="name@bank" autoCapitalize="off" autoCorrect="off" spellCheck={false}
                  className="flex-1 min-w-0 h-10 rounded-full bg-well px-4 text-[15px] outline-none" />
                <button disabled={busy || upi.trim() === (info.upi_id ?? "")} className="pill h-10 text-[14px] shadow-none">Save</button>
              </div>
              <div className="text-[12.5px] leading-[18px] text-muted">When a checkout offers Pay by UPI ID, Odie enters it and the request arrives in your UPI app, to approve with your PIN. It isn't a secret, and it's never kept as a memory.</div>
            </form>
            <div className="px-4 py-3 text-[12.5px] leading-[18px] text-muted">We suggest a local model, and a separate chat thread for signed-in tasks. Odie asks before contacting another site after reading a signed-in page, and before ordering, paying, booking or sending.</div>
          </>
        )}
      </div>
      {error && <div className="text-[13px] text-warn-ink px-1.5">{error}</div>}
      {createPortal(<AnimatePresence>{sheet && <Disclaimer info={info} onClose={(on) => { setSheet(false); if (on) load(); }} />}</AnimatePresence>, document.body)}
      {live && <LiveView tab={live.tab} site={live.start} start={live.start} chat={false} onClose={() => { setLive(null); load(); }} />}
    </section>
  );
}

/** The disclaimer (spec Part 0): Turn on stays off until the box is ticked; the server checks the version it showed. */
function Disclaimer({ info, onClose }: { info: SignIn; onClose: (on: boolean) => void }) {
  const [ticked, setTicked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [terms, rest] = splitAccept(info.disclaimer);
  async function turnOn() {
    setBusy(true); setError("");
    const r = await call("/api/browser/signin", "POST", { accepted: ticked, version: info.version });
    setBusy(false);
    if (r.ok) onClose(true);
    else setError(r.data.detail || "That didn't work. Try again.");
  }
  return (
    <motion.div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/50" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
      onClick={() => onClose(false)}>
      <motion.div role="dialog" aria-modal="true" aria-label="Signed-in browsing" onClick={(e) => e.stopPropagation()}
        initial={{ y: 40 }} animate={{ y: 0 }} exit={{ y: 40 }} transition={{ duration: 0.22 }}
        className="w-full sm:max-w-[520px] max-h-[88vh] overflow-y-auto bg-ground border border-line shadow-2xl rounded-t-[28px] sm:rounded-[28px] p-5 pb-[max(20px,env(safe-area-inset-bottom))] flex flex-col gap-4">
        <div className="md text-[14.5px] leading-[21px]"><ReactMarkdown>{terms}</ReactMarkdown></div>
        <label className="flex items-start gap-3 rounded-2xl bg-well px-3.5 py-3 cursor-pointer">
          <input type="checkbox" checked={ticked} onChange={(e) => setTicked(e.target.checked)} className="mt-0.5 w-5 h-5 shrink-0 accent-[var(--t-brand)]" />
          <span className="md text-[14px] leading-[20px]"><ReactMarkdown>{rest}</ReactMarkdown></span>
        </label>
        {error && <div className="text-[13px] text-warn-ink">{error}</div>}
        <div className="flex gap-2">
          <button onClick={() => onClose(false)} className="pill flex-1 h-12 text-[15px] shadow-none">Not now</button>
          <button onClick={turnOn} disabled={busy || !canTurnOn(ticked, info.version, info.version)} className="pill pill-solid flex-1 h-12 text-[15px] shadow-none disabled:opacity-40">
            {busy && <span className="spinner" />}Turn on
          </button>
        </div>
      </motion.div>
    </motion.div>
  );
}

/** The terms, and the closing "I understand and accept these risks." paragraph that goes beside the checkbox. */
export function splitAccept(text: string): [string, string] {
  const at = text.lastIndexOf("**I understand");
  return at < 0 ? [text, "I understand and accept these risks."] : [text.slice(0, at).trim(), text.slice(at).trim()];
}
