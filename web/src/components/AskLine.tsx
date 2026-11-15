import { useState } from "react";
import { postJSON } from "../api";
import type { JobAsk } from "../bots";
import { LiveView } from "./LiveView";

/** One question a bot waits on, answerable where it shows (Today's Bots card): a tap -> Allow / Deny; a sign-in ->
 * Sign in (the live view of its page) / Done / Skip; a code -> a link to the bot's chat, where the code box is. Only
 * these buttons answer a question (odie/workers/asks.py). */
export function AskLine({ a, onAnswered }: { a: JobAsk; onAnswered: () => void }) {
  const [signing, setSigning] = useState(false);
  async function answer(said: "yes" | "no") {
    try { await postJSON(`/api/jobs/asks/${a.id}`, { answer: said }); } catch { /* answered elsewhere, or gone */ }
    onAnswered();
  }
  const chat = a.bot && a.conv ? `#bot/${a.bot}/${a.conv}` : a.bot ? `#bot/${a.bot}` : "#bots";
  const btn = "h-9 px-3.5 rounded-[12px] text-[13.5px] font-semibold";
  return (
    <div className="rounded-[16px] bg-warn-tint px-3 py-2.5 flex flex-col gap-2">
      <a href={chat} className="text-[13.5px] leading-[18px]"><b>{a.bot ?? "A bot"}</b> asks: {a.text}</a>
      {a.why && <div className="text-[12px] text-muted">{a.why}</div>}
      <div className="flex gap-2">
        {a.kind === "tap" && (
          <>
            <button onClick={() => void answer("no")} className={`pill ${btn}`}>Deny</button>
            <button onClick={() => void answer("yes")} className={`${btn} bg-ember text-on-ember`}>Allow</button>
          </>
        )}
        {a.kind === "sign_in" && (
          <>
            {a.card?.tab && <button onClick={() => setSigning(true)} className={`${btn} bg-ember text-on-ember`}>Sign in</button>}
            <button onClick={() => void answer("yes")} className={`pill ${btn}`}>Done</button>
            <button onClick={() => void answer("no")} className={`pill ${btn}`}>Skip</button>
          </>
        )}
        {a.kind === "secret" && <a href={chat} className={`${btn} bg-ember text-on-ember inline-flex items-center`}>Type it in {a.bot ?? "the bot"}'s chat</a>}
      </div>
      {signing && a.card?.tab && (
        <LiveView tab={a.card.tab} site={a.site ?? ""} chat={false} onClose={(r) => { setSigning(false); if (r?.done) void answer("yes"); }} />
      )}
    </div>
  );
}
