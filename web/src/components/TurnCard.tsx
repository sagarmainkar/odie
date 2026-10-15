import { useEffect, useState } from "react";
import { getJSON } from "../api";
import type { Media } from "../media";
import { sendInChat, signedInLine, turnTitle, upiDetails, upiLink, type SavedLogin } from "../signin";
import { LiveView } from "./LiveView";
import { SignInSheet } from "./SignInSheet";
import { Tile } from "./Tile";

/** "Your turn" (odie/agent/tools/browser.py): a site wants the user signed in. Sign in opens Odie's own sign-in box;
 * Open the page is the live view (for a captcha or an odd page). A saved login that signed in by itself shows done. */
export function TurnCard({ m }: { m: Media }) {
  const [sheet, setSheet] = useState(false);
  const [live, setLive] = useState(false);
  const [done, setDone] = useState(m.state === "done");
  const [username, setUsername] = useState("");
  const site = m.site || "the site";
  useEffect(() => {  // a saved login that failed: the sheet starts with its username (never sent to the AI)
    if (m.state !== "failed") return;
    getJSON<{ logins: SavedLogin[] }>("/api/browser/logins").then((r) => setUsername(r.logins.find((l) => l.site === site)?.username ?? "")).catch(() => {});
  }, [m.state, site]);
  const finish = () => { setDone(true); sendInChat(signedInLine(site, true)); };
  const state = done ? "done" : m.state;
  return (
    <div className="glass rounded-[22px] p-3.5 flex flex-col gap-2.5">
      <div className="flex items-center gap-3">
        <Tile icon="lock" color={done ? "green" : "blue"} />
        <div className="flex-1 min-w-0">
          <div className="text-[15px] font-semibold leading-5 break-words">{turnTitle(state, site, !!m.auto && m.state === "done")}</div>
          <div className="text-[13px] leading-[18px] text-muted">{done ? "Odie carries on from here." : m.why}</div>
        </div>
      </div>
      {!done && m.tab && (
        <>
          {m.state === "captcha" ? (
            <button onClick={() => setLive(true)} className="pill pill-solid h-11 text-[15px] shadow-none">Open the page</button>
          ) : (
            <button onClick={() => setSheet(true)} className="pill pill-solid h-11 text-[15px] shadow-none">{m.state === "code" ? "Enter the code" : "Sign in"}</button>
          )}
          {m.state !== "captcha" && <button onClick={() => setLive(true)} className="text-[13px] text-muted self-start">Open the page instead</button>}
        </>
      )}
      {sheet && m.tab && (
        <SignInSheet tab={m.tab} site={site} username={username} startWith={m.state === "code" ? "code" : "login"}
          onClose={(r) => { setSheet(false); if (r?.status === "signed_in") finish(); else if (r?.status === "open_page") setLive(true); }} />
      )}
      {live && m.tab && <LiveView tab={m.tab} site={site} chat onClose={(r) => { setLive(false); if (r?.done) setDone(true); }} />}
    </div>
  );
}

/** A checkout tried to open a UPI app (odie/browser/engine.py upi_link): on the phone, this opens it, filled in. */
export function PayCard({ m }: { m: Media }) {
  const link = upiLink(m.url ?? "");
  if (!link) return null;
  const { payee, amount } = upiDetails(link);
  return (
    <a href={link} className="glass rounded-[22px] p-3.5 flex items-center gap-3 active:opacity-80">
      <Tile icon="rupee" color="green" />
      <span className="flex-1 min-w-0">
        <b className="block text-[15px] font-semibold leading-5">Pay {amount ? `₹${amount} ` : ""}in your UPI app</b>
        <span className="block text-[13px] leading-[18px] text-muted">{payee ? `To ${payee}. ` : ""}Opens GPay, PhonePe or Paytm on your phone; you approve it with your PIN.</span>
      </span>
    </a>
  );
}
