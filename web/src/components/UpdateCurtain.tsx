import { motion } from "framer-motion";
import { useEffect, useState } from "react";
import { getJSON } from "../api";
import { reloadFresh, updateLanded } from "../update";
import { Avatar } from "./Avatar";

const POLL_MS = 3000;
const GIVE_UP_MS = 5 * 60 * 1000;  // an update takes about a minute; after five, something went wrong

/** The whole app under a curtain while `odie update` runs: fetch, build, restart. It watches /api/health for the
 *  new version, then forgets the old app shell and reloads. Nothing else is tappable meanwhile, on purpose. */
export function UpdateCurtain({ from, to }: { from: string; to: string }) {
  const [stuck, setStuck] = useState(false);
  useEffect(() => {
    const started = Date.now();
    let done = false;
    const look = async () => {
      if (done) return;
      const health = await getJSON<{ version?: string }>("/api/health").catch(() => null);  // the restart: no answer for a while
      if (updateLanded(from, health)) { done = true; void reloadFresh(); return; }
      if (Date.now() - started > GIVE_UP_MS) { done = true; setStuck(true); }
    };
    const timer = setInterval(() => void look(), POLL_MS);
    return () => { done = true; clearInterval(timer); };
  }, [from]);
  return (
    <motion.div role="dialog" aria-label="Updating Odie" aria-busy={!stuck} initial={{ opacity: 0 }} animate={{ opacity: 1 }}
      className="fixed inset-0 z-50 bg-overlay backdrop-blur-xl flex items-center justify-center px-6">
      <div className="glass glass-solid rounded-[26px] px-6 py-7 w-full max-w-[420px] flex flex-col items-center text-center gap-3 shadow-[0_24px_60px_-24px_rgba(60,40,20,.45)]">
        <Avatar size={64} state={stuck ? "idle" : "thinking"} />
        {stuck ? (
          <>
            <div className="text-[19px] font-bold tracking-[-0.01em]">Still on {from}</div>
            <div className="text-[14px] leading-5 text-muted">The update to {to} hasn't landed after five minutes: it may have rolled back. On the Mac, <span className="font-mono">odie logs</span> says what happened.</div>
            <button type="button" onClick={() => void reloadFresh()} className="pill pill-solid h-11 px-6 text-[15px] shadow-none mt-1">Reload</button>
          </>
        ) : (
          <>
            <div className="text-[19px] font-bold tracking-[-0.01em]">Updating Odie…</div>
            <div className="text-[14px] leading-5 text-muted">{from} → {to}. Fetching, building and restarting takes about a minute. Odie comes back on its own.</div>
            <span className="spinner mt-1" />
          </>
        )}
      </div>
    </motion.div>
  );
}
