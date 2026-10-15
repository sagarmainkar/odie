import { useEffect, useState } from "react";
import { getJSON } from "../api";
import { Icon } from "./Tile";

/** The Connect Google card under a message that needs it: one tap to Google's consent and back to Chat. */
export function ConnectCard({ since }: { since?: number }) {
  const [done, setDone] = useState(false);
  useEffect(() => {
    getJSON<{ connected: boolean; connected_at?: string | null }>("/api/google/status").then((g) => {
      if (g.connected && g.connected_at && since && Date.parse(g.connected_at) / 1000 > since) setDone(true);
    }).catch(() => {});
  }, [since]);
  useEffect(() => {  // Chat relays the server's "connected" event (one live connection for the whole screen)
    const on = () => setDone(true);
    window.addEventListener("odie:google-connected", on);
    return () => window.removeEventListener("odie:google-connected", on);
  }, []);
  return (
    <div className="glass rounded-[22px] px-4 py-3.5 flex items-center gap-3">
      <span className="w-10 h-10 rounded-[13px] grid place-items-center bg-[#e8f0fe] text-[#1a73e8] shrink-0"><Icon name={done ? "check" : "mail"} size={18} stroke={2.2} /></span>
      <div className="flex-1 min-w-0">
        <b className="text-[15px] font-semibold block">{done ? "Google connected" : "Connect Google"}</b>
        <span className="text-[12.5px] text-muted">{done ? "Mail and calendar work again." : "Gmail and Calendar, in one step."}</span>
      </div>
      {!done && <a href="/api/google/connect?from=chat" className="pill pill-solid h-10 text-[14px] shadow-none shrink-0">Connect</a>}
    </div>
  );
}
