import { useState } from "react";
import type { Media } from "../media";
import { pageText, setSignin } from "../trackers";
import { Tile } from "./Tile";

/** "Check this page signed in?" (odie/trackers/signed_in.py): only this tap lets a tracker sign in; the AI can't. */
export function TrackerSignInCard({ m }: { m: Media }) {
  const [answer, setAnswer] = useState<"allowed" | "not_now" | null>(null);
  const [problem, setProblem] = useState("");
  const site = m.site || "the site";
  async function tap(allow: boolean) {
    if (!m.tracker_id) return;
    const why = await setSignin(m.tracker_id, allow);
    if (why) { setProblem(why); return; }
    setProblem("");
    setAnswer(allow ? "allowed" : "not_now");
  }
  return (
    <div className="glass rounded-[22px] p-3.5 flex flex-col gap-2.5">
      <div className="flex items-center gap-3">
        <Tile icon="bell" color={answer === "allowed" ? "green" : "yellow"} />
        <div className="flex-1 min-w-0">
          <div className="text-[15px] font-semibold leading-5 break-words">
            {answer === "allowed" ? `Checking it signed in to ${site}` : answer === "not_now" ? "Checking without signing in" : `Check this page signed in to ${site}?`}
          </div>
          <div className="text-[13px] leading-[18px] text-muted break-all">{pageText(m.page ?? "")}</div>
        </div>
      </div>
      {!answer && (
        <>
          <div className="text-[13px] leading-[18px] text-muted">Odie opens only this page, reads it and tells you what changed. It never clicks, types or buys.</div>
          <div className="flex gap-2">
            <button onClick={() => void tap(true)} className="pill pill-solid h-11 flex-1 text-[15px] shadow-none">Allow</button>
            <button onClick={() => void tap(false)} className="pill pill-flat h-11 flex-1 text-[15px]">Not now</button>
          </div>
        </>
      )}
      {answer && <div className="text-[13px] leading-[18px] text-muted">You can change this on Today.</div>}
      {problem && <div className="text-[13px] leading-[18px] text-warn">{problem}</div>}
    </div>
  );
}
