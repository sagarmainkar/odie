import { useEffect, useState } from "react";
import { getJSON, postJSON, putJSON } from "../api";
import { ASK_TEXT, afterAllow, currentPosition, geolocationSupported, shouldAsk, shouldRefresh, type LocationInfo } from "../location";
import { Tile } from "./Tile";

/** Sends this browser's position to the server, once; a browser that can't or won't is silent (the server keeps the last place). */
async function sendPosition(): Promise<LocationInfo | null> {
  const got = await currentPosition();
  if (got === "denied" || got === null) return null;
  try { return await postJSON<LocationInfo>("/api/location", got); } catch { return null; }
}

/** Under the composer: the one ask for where the user is, shown until answered; afterwards a silent refresh on each open. */
export function LocationAsk() {
  const [info, setInfo] = useState<LocationInfo | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let live = true;
    getJSON<LocationInfo>("/api/location").then((x) => {
      if (!live) return;
      setInfo(x);
      if (shouldRefresh(x, geolocationSupported())) void sendPosition();  // allowed earlier: refresh quietly
    }).catch(() => {});
    return () => { live = false; };
  }, []);
  if (!shouldAsk(info, geolocationSupported())) return null;
  async function allow() {
    setBusy(true);
    const got = await currentPosition();  // the browser asks its own question here
    try {
      const next = afterAllow(got);
      if (next === "send" && got !== "denied" && got !== null) setInfo(await postJSON<LocationInfo>("/api/location", got));
      if (next === "decline") setInfo(await putJSON<LocationInfo>("/api/location", { on: false }));  // the browser won't ask again; neither will this line
    } catch { /* the line stays until the server hears */ }
    finally { setBusy(false); }
  }
  async function notNow() {
    setBusy(true);
    try { setInfo(await putJSON<LocationInfo>("/api/location", { on: false })); } catch { /* the line stays until the server hears */ }
    finally { setBusy(false); }
  }
  return (
    <div className="glass rounded-[22px] mx-3 mb-2 px-3.5 py-3 flex items-start gap-3 rise">
      <Tile icon="pin" color="green" small />
      <div className="flex-1 min-w-0">
        <div className="text-[13px] leading-[18px] text-muted">{ASK_TEXT}</div>
        <div className="flex gap-3 mt-1.5">
          <button type="button" disabled={busy} onClick={() => void allow()} className="h-8 px-1 text-[13px] font-semibold text-ember-text disabled:opacity-50">Allow</button>
          <button type="button" disabled={busy} onClick={() => void notNow()} className="h-8 px-1 text-[13px] font-medium text-muted disabled:opacity-50">Not now</button>
        </div>
      </div>
    </div>
  );
}
