import { motion } from "framer-motion";
import { useEffect, useState } from "react";
import { MODE_COPY, readMode, setMode, useApprovalsMode, type ApprovalsMode } from "../approvalsMode";

const MODES: ApprovalsMode[] = ["careful", "smart"];

/** Settings → Approvals: Careful (every tap, as always) or Smart (routine work runs on its own; the risky list still
 * asks). The chosen one is saved at once; the line under the control explains the current choice. */
export function ApprovalsSection() {
  const mode = useApprovalsMode();
  const [error, setError] = useState("");
  const [unread, setUnread] = useState(false);  // the setting couldn't be read: say so, and let a tap still try to save
  useEffect(() => { readMode().catch(() => { setUnread(true); setError("Couldn't read this setting; a tap still saves it."); }); }, []);
  async function choose(next: ApprovalsMode) {
    setError("");
    try { await setMode(next); } catch (e) { setError((e as Error).message || "Couldn't save that."); }
  }
  const shown = mode ?? "careful";
  return (
    <section className="flex flex-col gap-2">
      <div className="text-[13px] leading-5 font-bold text-muted px-1.5">Approvals</div>
      <div className="glass rounded-[26px] overflow-hidden">
        <div className="p-3 flex flex-col gap-3">
          <div className="bg-well rounded-[14px] p-1 flex gap-1" role="radiogroup" aria-label="Approvals">
            {MODES.map((m) => (
              <button key={m} role="radio" aria-checked={m === shown} disabled={mode === null && !unread} onClick={() => void choose(m)}
                className={`relative flex-1 h-11 rounded-[10px] text-[14px] font-medium disabled:opacity-40 ${m === shown ? "text-ink" : "text-muted"}`}>
                {m === shown && <motion.span layoutId="approvals-seg" transition={{ duration: 0.2 }} className="absolute inset-0 rounded-[10px] bg-surface" style={{ boxShadow: "var(--t-shadow-card)" }} />}
                <span className="relative">{MODE_COPY[m].title}</span>
              </button>
            ))}
          </div>
          <div className="text-[13px] leading-[18px] px-1 text-muted">{MODE_COPY[shown].line}</div>
          {error && <div className="text-[13px] leading-[18px] px-1 text-warn-ink">{error}</div>}
        </div>
      </div>
    </section>
  );
}
