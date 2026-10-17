import { motion } from "framer-motion";
import { useEffect, useState } from "react";
import { postJSON } from "../api";
import { mediaUrl } from "../media";
import { Tile, type IconName, type TileColor } from "./Tile";
import { userLocale } from "../locale";

export type Approval = {
  id: number; tool: string; summary: string; status: string; risk?: string; created_at?: string;
  detail?: Record<string, unknown> | null; provenance?: { from: string; subject: string }[] | null; result_text?: string | null;
};

const TOOL_WORD: Record<string, string> = { gmail_send_draft: "Send", gmail_trash: "Trash", calendar_create_event: "Invite", calendar_respond: "RSVP", run_shell: "Run", install_skill: "Install",
  web_search: "Search", web_fetch: "Open", browser_open: "Open", find_images: "Photos", find_clips: "Clips", browser_click: "Click", browser_type: "Submit", speak: "Read aloud" };

function toolTileFor(tool: string): { icon: IconName; color: TileColor } {
  if (tool === "run_shell") return { icon: "terminal", color: "ink" };
  if (tool === "install_skill") return { icon: "spark", color: "violet" };
  if (tool === "gmail_trash") return { icon: "trash", color: "ink" };
  if (tool.startsWith("calendar")) return { icon: "cal", color: "orange" };
  if (tool === "browser_click" || tool === "browser_type") return { icon: "lock", color: "orange" };  // on a signed-in site
  if (tool.startsWith("web_") || tool === "browser_open" || tool === "find_images" || tool === "find_clips" || tool === "speak") return { icon: "globe", color: "blue" };
  return { icon: "send", color: "blue" };
}

function Warn() {
  return <svg className="shrink-0 mt-0.5 text-warn-ink" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0zM12 9v4M12 17h.01" /></svg>;
}

function expiresIn(created?: string): string {
  if (!created) return "";
  const left = new Date(created).getTime() + 24 * 3600e3 - Date.now();
  if (!(left > 0)) return "";
  const h = Math.floor(left / 3600e3);
  return h >= 1 ? `Expires in ${h} h` : `Expires in ${Math.max(1, Math.round(left / 60e3))} min`;
}

const STATUS: Record<string, { label: string; text: string; tint: string }> = {
  pending: { label: "Needs your tap", text: "text-gold-text", tint: "bg-gold-tint" },
  approved: { label: "Done", text: "text-moss-text", tint: "bg-moss-tint" },
  rejected: { label: "Declined", text: "text-muted", tint: "bg-surface-2" },
  expired: { label: "Expired", text: "text-muted", tint: "bg-surface-2" },
};

const EASE = [0.2, 0.8, 0.2, 1] as const;

export function ApprovalCard({ a, onDecided, showResult = true }: { a: Approval; onDecided?: (id: number, status: string) => void; compact?: boolean; showResult?: boolean }) {
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState(a.status);
  const [result, setResult] = useState<string | null>(a.result_text ?? null);
  // Follow live updates (approved elsewhere, finished, expired): the card used to read its status only once.
  useEffect(() => { setStatus(a.status); }, [a.status]);
  useEffect(() => { if (a.result_text) setResult(a.result_text); }, [a.result_text]);
  const [showAll, setShowAll] = useState(false);
  const [allowedUntil, setAllowedUntil] = useState<string | null>(null);
  const fromMail = a.risk === "from_email" && (a.provenance?.length ?? 0) > 0;
  const unknown = a.risk === "unknown";
  const careful = fromMail || unknown;
  const body = typeof a.detail?.body === "string" ? (a.detail.body as string) : null;
  const command = typeof a.detail?.command === "string" ? (a.detail.command as string) : null;
  const cwd = typeof a.detail?.cwd === "string" ? (a.detail.cwd as string) : null;
  const shot = typeof a.detail?.shot === "string" ? (a.detail.shot as string) : null;  // the signed-in page it would act on
  const why = typeof a.detail?.why === "string" ? (a.detail.why as string) : null;
  const latest = a.provenance?.[0];
  const st = STATUS[status] ?? STATUS.expired;

  async function decide(approve: boolean, allowMinutes?: number) {
    setBusy(true);
    try {
      // Answers at once; the paused turn resumes on the server and its reply arrives as a normal message.
      const r = await postJSON<{ status?: string; allowed_until?: string }>(`/api/approvals/${a.id}/decide`, { approve, allow_minutes: allowMinutes });
      const s = r.status ?? (approve ? "approved" : "rejected");
      if (r.allowed_until) setAllowedUntil(new Date(r.allowed_until).toLocaleTimeString(userLocale(), { hour: "numeric", minute: "2-digit" }));
      setStatus(s); onDecided?.(a.id, s);
    } catch (e) { setResult((e as Error).message); } finally { setBusy(false); }
  }

  const tile = toolTileFor(a.tool);

  if (status !== "pending") {
    // Decided: collapse to one quiet row, with the outcome underneath.
    const ok = status === "approved";
    return (
      <motion.div layout transition={{ duration: 0.24, ease: EASE }}
        className={`glass rounded-[22px] px-3.5 py-3 flex flex-col gap-1 ${ok ? "bg-[linear-gradient(160deg,var(--t-good-tint),transparent_70%)]" : ""}`}>
        <div className="flex items-center gap-2.5">
          <Tile icon={ok ? "check" : "x"} color={ok ? "green" : "ink"} small />
          <span className="text-[14px] text-muted flex-1 min-w-0 truncate"><b className={`font-bold ${ok ? "text-good" : "text-ink-2"}`}>{st.label}</b> · {a.summary}</span>
        </div>
        {allowedUntil && <div className="text-[13px] leading-[18px] text-muted pl-[42px]">Commands in this chat run without asking until {allowedUntil}, except ones that read secrets, delete, or send data out.</div>}
        {showResult && result && <div className="text-[13px] leading-[18px] text-muted pl-[42px]">{result}</div>}
      </motion.div>
    );
  }

  const primary = "pill pill-solid shadow-none";
  const secondary = "pill shadow-none";
  const banner = "flex items-start gap-2 bg-warn-tint rounded-2xl px-3 py-2 text-[13px] leading-[18px] text-ink-2";
  return (
    <motion.div layout initial={{ opacity: 0, y: 12, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} transition={{ duration: 0.24, ease: EASE }}
      className={`glass rounded-[26px] p-4 flex flex-col gap-3 bg-[linear-gradient(160deg,var(--t-warn-tint),transparent_70%)] ${careful ? "!border-gold" : "!border-[rgba(255,178,63,.35)]"}`}>
      <div className="flex items-center gap-3">
        <Tile icon={tile.icon} color={tile.color} />
        <div className="flex-1 min-w-0">
          <div className="text-[15px] font-bold leading-snug break-words">{a.summary}</div>
          <div className="text-[12.5px] text-muted">{a.tool === "run_shell" ? "On this computer" : a.tool === "install_skill" ? "New skill · read it, then approve"
            : typeof a.detail?.app === "string" ? `${a.detail.app} · needs your tap` : `${TOOL_WORD[a.tool] ?? a.tool} · needs your tap`}</div>
        </div>
      </div>
      {fromMail && latest && (
        <div className={banner}><Warn /><span>Odie read mail from <b className="font-semibold">{latest.from}</b> ({latest.subject}) just before this. Make sure it's what you asked for, not what the mail asked for.</span></div>
      )}
      {a.risk === "mail_earlier" && latest && (
        <div className="text-[13px] leading-[18px] text-muted">Earlier in this conversation Odie read mail from {latest.from.replace(/<.*>/, "").trim()}. Just so you know.</div>
      )}
      {unknown && <div className={banner}><Warn /><span>I can't show you what this draft contains. Safer to decline and ask Odie to draft it again.</span></div>}
      {why && <div className={banner}><Warn /><span>{why}</span></div>}
      {shot && <img src={mediaUrl({ id: shot })} alt="The page it would act on" className="w-full max-h-[260px] object-cover object-top rounded-2xl border border-line" />}
      {body && (
        <div className="bg-well rounded-2xl px-3.5 py-2.5">
          <div className={`${a.tool === "install_skill" ? "font-mono text-[12px] leading-[17px] overflow-x-auto" : "text-[15px] leading-[22px]"} text-ink-2 whitespace-pre-wrap ${showAll ? "" : "line-clamp-6"}`}>{body}</div>
          {(body.split("\n").length > 6 || body.length > 360) && (
            <button onClick={() => setShowAll((v) => !v)} className="mt-1 text-[13px] text-ember-text font-semibold min-h-8">{showAll ? "Show less" : "Show all"}</button>
          )}
        </div>
      )}
      {command && (
        <div className="flex flex-col gap-1">
          {cwd && <div className="text-[12px] text-dim font-mono">in {cwd}</div>}
          <pre className="font-mono text-[13px] leading-[1.55] bg-well rounded-2xl px-3.5 py-3 whitespace-pre-wrap break-words">{command}</pre>
        </div>
      )}
      <div className="flex gap-2 pt-1">
        <button onClick={() => decide(true)} disabled={busy} className={`flex-1 h-12 text-[16px] ${careful ? secondary : primary}`}>
          {busy && <span className="spinner" />}{a.tool === "run_shell" ? "Run it" : a.tool === "gmail_send_draft" ? "Send it" : "Do it"}
        </button>
        <button onClick={() => decide(false)} disabled={busy} className={`flex-1 h-12 text-[16px] ${careful ? primary : secondary}`}>
          {careful ? "Don't do this" : "Not now"}
        </button>
      </div>
      {a.tool === "run_shell" && !careful && (
        <button onClick={() => decide(true, 30)} disabled={busy} className="w-full text-center text-[13.5px] font-semibold text-muted py-1.5 disabled:opacity-50">
          Run it, and allow commands for 30 min
        </button>
      )}
      <div className="text-[12px] leading-4 text-dim -mt-1">
        Sending, deleting, invites, commands, app actions and new code always ask first; reading never does. Every action is logged.
        {expiresIn(a.created_at) && <> · {expiresIn(a.created_at)}</>}
      </div>
    </motion.div>
  );
}
