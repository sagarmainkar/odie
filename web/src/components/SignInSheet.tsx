import { motion } from "framer-motion";
import { useState } from "react";
import { createPortal } from "react-dom";
import { loginStatusText, type LoginStatus } from "../signin";

export type SheetResult = { status: "signed_in"; site: string } | { status: "open_page" };

/** Odie's own sign-in box (spec "Sign in for me", Part 3): ordinary fields, so paste and iPhone AutoFill work, and
 * Odie's browser fills the site. Nothing typed here reaches the AI. */
export function SignInSheet(props: { tab: string; site: string; username?: string; startWith?: "login" | "code"; onClose: (r: SheetResult | null) => void }) {
  return createPortal(<Sheet {...props} />, document.body);  // on the page itself: a card's backdrop filter would trap it
}

function Sheet({ tab, site, username = "", startWith = "login", onClose }: { tab: string; site: string; username?: string; startWith?: "login" | "code"; onClose: (r: SheetResult | null) => void }) {
  const [user, setUser] = useState(username);
  const [pass, setPass] = useState("");
  const [code, setCode] = useState("");
  const [remember, setRemember] = useState(true);
  const [phase, setPhase] = useState<"login" | "code">(startWith);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [openPage, setOpenPage] = useState(false);

  async function send(path: string, body: unknown) {
    setBusy(true); setNote(""); setOpenPage(false);
    try {
      const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) { setNote(data.detail || "That didn't work. Try again."); return; }
      const status = data.status as LoginStatus;
      if (status === "signed_in") { if (data.warning) window.alert(data.warning); onClose({ status, site }); return; }
      if (status === "code") { setPhase("code"); setPass(""); setNote(loginStatusText("code", site)); return; }
      setNote(loginStatusText(status, site));
      setOpenPage(status === "captcha" || status === "wrong_site");
      if (status === "expired") setPhase("login");
    } catch {
      setNote("Odie didn't answer. Try again.");
    } finally {
      setBusy(false);
    }
  }
  const field = "w-full h-12 rounded-2xl bg-well px-4 text-[16px] outline-none";  // 16px: an iPhone doesn't zoom into it
  return (
    <motion.div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/50" initial={{ opacity: 0 }} animate={{ opacity: 1 }}
      onClick={() => onClose(null)}>
      <motion.form role="dialog" aria-modal="true" aria-label={`Sign in to ${site}`} onClick={(e) => e.stopPropagation()}
        initial={{ y: 40 }} animate={{ y: 0 }} transition={{ duration: 0.22 }}
        onSubmit={(e) => { e.preventDefault(); if (phase === "login") void send(`/api/browser/sign-in/${encodeURIComponent(tab)}`, { site, username: user, password: pass, remember }); else void send(`/api/browser/sign-in/${encodeURIComponent(tab)}/code`, { code }); }}
        className="w-full sm:max-w-[440px] bg-ground border border-line shadow-2xl rounded-t-[28px] sm:rounded-[28px] p-5 pb-[max(20px,env(safe-area-inset-bottom))] flex flex-col gap-3">
        <div className="text-[17px] font-bold">Sign in to {site}</div>
        {phase === "login" ? (
          <>
            <input className={field} name="username" autoComplete="username" autoCapitalize="off" autoCorrect="off" spellCheck={false}
              placeholder="Email or phone" aria-label="Email or phone" value={user} onChange={(e) => setUser(e.target.value)} />
            <input className={field} name="password" type="password" autoComplete="current-password" placeholder="Password"
              aria-label="Password" value={pass} onChange={(e) => setPass(e.target.value)} />
            <label className="flex items-center gap-3 text-[14px]">
              <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} className="w-5 h-5 accent-[var(--t-brand)]" />
              Remember in Odie's vault (on this Mac's Keychain)
            </label>
          </>
        ) : (
          <input className={field} name="code" autoComplete="one-time-code" inputMode="numeric" placeholder="Code" aria-label="Code"
            value={code} onChange={(e) => setCode(e.target.value)} />
        )}
        {note && <div className="text-[13.5px] leading-[19px] text-ink-2">{note}</div>}
        <div className="flex gap-2">
          {openPage ? (
            <button type="button" onClick={() => onClose({ status: "open_page" })} className="pill pill-solid flex-1 h-12 text-[15px] shadow-none">Open the page</button>
          ) : (
            <button type="submit" disabled={busy || (phase === "login" ? !user.trim() || !pass : !code.trim())}
              className="pill pill-solid flex-1 h-12 text-[15px] shadow-none disabled:opacity-40">
              {busy && <span className="spinner" />}{phase === "login" ? "Sign in" : "Send the code"}
            </button>
          )}
          <button type="button" onClick={() => onClose(null)} className="pill h-12 px-5 text-[15px] shadow-none">Cancel</button>
        </div>
        <div className="text-[12px] leading-4 text-dim">Odie's browser types this into {site} itself. The AI never sees it.</div>
      </motion.form>
    </motion.div>
  );
}
