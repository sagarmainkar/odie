import { useEffect, useRef, useState } from "react";
import { Tile } from "../components/Tile";
import { codeFromHash, typedCode, type PairStatus } from "../devices";

const input = "h-12 px-3.5 rounded-[14px] bg-well border border-line outline-none text-[16px] focus:border-line-2";

async function pair(url: string, body: unknown): Promise<string | null> {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (r.ok) return null;
  return (await r.json().catch(() => ({}))).detail || "That didn't work. Try again.";
}

/** What a browser that isn't paired sees: a code (typed, or from a QR code's link) or the recovery passcode pairs it. */
export function Private({ status }: { status: PairStatus | null }) {
  const fromLink = codeFromHash(location.hash);
  const [code, setCode] = useState(fromLink ?? "");
  const [words, setWords] = useState("");
  const [name, setName] = useState("");
  const [withPasscode, setWithPasscode] = useState(false);
  const [error, setError] = useState(new URLSearchParams(location.search).get("pair") === "used" ? "That setup link was already used." : "");
  const [busy, setBusy] = useState(false);
  const tried = useRef(false);

  async function go(url: string, body: unknown) {
    setBusy(true); setError("");
    const err = await pair(url, body);
    if (err) { setBusy(false); setError(err); return; }
    location.replace("/");  // in: start fresh, without the code in the address
  }
  // A QR code's link pairs at once.
  useEffect(() => {
    if (fromLink && !tried.current) { tried.current = true; void go("/api/pair/code", { code: fromLink, name: "" }); }
  }, [fromLink]);

  const ready = withPasscode ? words.trim().split(/\s+/).length >= 4 : code.length === 9;
  return (
    <div className="h-full overflow-y-auto no-scrollbar px-[18px] safe-top pb-8 flex flex-col items-center justify-center gap-6">
      <div className="flex flex-col items-center text-center gap-2 max-w-[340px]">
        <Tile icon="lock" color="ink" />
        <h1 className="text-[22px] font-bold tracking-[-0.015em]">This Odie is private</h1>
        <p className="text-[14.5px] leading-[21px] text-muted">Only the devices you've paired can use it. Pair this one with a code from a device that's already paired: Settings → Devices → Add a device.</p>
      </div>
      <form className="glass rounded-[26px] p-4 w-full max-w-[380px] flex flex-col gap-2.5"
        onSubmit={(e) => { e.preventDefault(); if (ready && !busy) void (withPasscode ? go("/api/pair/passcode", { passcode: words, name }) : go("/api/pair/code", { code, name })); }}>
        {withPasscode ? (
          <input value={words} onChange={(e) => setWords(e.target.value)} className={input} placeholder="The four words" aria-label="Recovery passcode"
            autoCapitalize="none" autoCorrect="off" autoComplete="off" spellCheck={false} />
        ) : (
          <input value={code} onChange={(e) => setCode(typedCode(e.target.value))} className={`${input} font-mono tracking-[0.18em] text-center text-[20px]`}
            placeholder="8-letter code" aria-label="Pairing code" autoCapitalize="characters" autoCorrect="off" autoComplete="one-time-code" spellCheck={false} />
        )}
        <input value={name} onChange={(e) => setName(e.target.value)} className={input} placeholder="A name for this device (optional)" aria-label="Device name" maxLength={40} />
        {error && <div className="text-[13px] text-warn-ink">{error}</div>}
        <button type="submit" disabled={!ready || busy} className="pill pill-solid h-12 text-[15px] shadow-none">{busy ? "Pairing…" : "Pair this device"}</button>
        {status?.passcode !== false ? (
          <button type="button" onClick={() => { setWithPasscode(!withPasscode); setError(""); }} className="self-center text-[13.5px] text-ember-text font-semibold py-1">
            {withPasscode ? "Use a pairing code instead" : "Use the recovery passcode instead"}
          </button>
        ) : status.devices > 0 && (
          <div className="text-[12.5px] leading-[18px] text-dim text-center">No recovery passcode was made, so a code from a paired device is the way in.</div>
        )}
      </form>
      {status?.devices === 0 && (
        <p className="text-[13px] leading-[19px] text-dim text-center max-w-[340px]">Nothing is paired yet. On the computer Odie runs on, open the setup link the installer gave you.</p>
      )}
    </div>
  );
}
