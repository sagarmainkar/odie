import { useCallback, useEffect, useState } from "react";
import { getJSON } from "../api";
import { lastSeen, loopback, needsPasscode, type Device, type NewCode, type PairStatus } from "../devices";
import { Tile } from "./Tile";

async function call(url: string, method: string, body?: unknown): Promise<{ ok: boolean; status: number; data: any }> {
  const r = await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
  return { ok: r.ok, status: r.status, data: await r.json().catch(() => ({})) };
}

/** Settings: the paired devices. Add one (a one-time code, as a QR code and as text), remove one, make a new recovery
 * passcode, and turn pairing on or off. */
export function DevicesSection() {
  const [status, setStatus] = useState<PairStatus | null>(null);
  const [list, setList] = useState<Device[] | null>(null);
  const [made, setMade] = useState<NewCode | null>(null);
  const [passcode, setPasscode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    getJSON<PairStatus>("/api/pair/status").then(setStatus).catch(() => {});
    getJSON<Device[]>("/api/devices").then(setList).catch(() => {});
  }, []);
  useEffect(() => { load(); }, [load]);

  async function run(fn: () => Promise<{ ok: boolean; data: any } | null>) {
    setBusy(true); setError("");
    const r = await fn();
    setBusy(false);
    if (r && !r.ok) setError(r.data.detail || "That didn't work. Try again.");
    load();
    return r;
  }
  const turn = (on: boolean) => {
    if (!on && !confirm("Turn off device pairing? Anyone who can reach this address could use Odie.")) return;
    void run(() => call("/api/devices/pairing", "PUT", { on }));
  };
  const remove = (d: Device) => void run(async () => {
    if (!confirm(d.this ? "Remove this device? This browser will need a code or the passcode to get back in." : `Remove ${d.name}? It will need a code or the passcode to get back in.`)) return null;
    let r = await call(`/api/devices/${d.id}`, "DELETE");
    if (r.status === 409) {
      if (!confirm(`${r.data.detail} Remove it anyway?`)) return null;
      r = await call(`/api/devices/${d.id}?confirm=1`, "DELETE");
    }
    if (r.ok && d.this) location.reload();
    return r;
  });
  const addDevice = () => void run(async () => {
    const r = await call("/api/devices/code", "POST");
    if (r.ok) setMade(r.data as NewCode);
    return r;
  });
  const newPasscode = () => void run(async () => {
    if (!confirm("Make a new recovery passcode? It replaces the old one.")) return null;
    const r = await call("/api/devices/passcode", "POST");
    if (r.ok) setPasscode(r.data.passcode);
    return r;
  });

  return (
    <section className="flex flex-col gap-2">
      <div className="text-[13px] leading-5 font-bold text-muted px-1.5">Devices</div>
      {status && !status.on && (
        <div className="glass rounded-[26px] px-4 py-3.5 flex flex-col gap-2.5">
          <div className="text-[15px] font-semibold">Turn on device pairing</div>
          <div className="text-[13px] leading-[19px] text-muted">Right now anyone who can reach this address can use Odie. With pairing on, only the devices you pair can. Pair your phone first (Add a device), then turn it on here: this browser is paired as you do.</div>
          <button disabled={busy} onClick={() => turn(true)} className="pill pill-solid h-10 text-[14px] shadow-none self-start">Turn on</button>
        </div>
      )}
      <div className="glass rounded-[26px] overflow-hidden">
        {list === null && <div className="px-4 py-3.5 text-[14px] text-muted">Loading…</div>}
        {list?.length === 0 && <div className="px-4 py-3.5 text-[14px] text-muted">No device is paired yet.</div>}
        {list?.map((d) => (
          <div key={d.id} className="flex items-center gap-3 px-4 py-3 min-h-14 border-b border-line">
            <Tile icon="lock" color={d.this ? "green" : "ink"} small />
            <div className="flex-1 min-w-0">
              <div className="text-[15px] leading-5 font-medium truncate">{d.name}{d.this && <span className="chip chip-good ml-2 align-middle">This device</span>}</div>
              <div className="text-[13px] leading-[18px] text-muted">{lastSeen(d.last_seen_at)}</div>
            </div>
            <button disabled={busy} onClick={() => remove(d)} className="text-[13.5px] font-semibold text-warn-ink shrink-0 h-11 px-1">Remove</button>
          </div>
        ))}
        {made ? (
          <div className="px-4 py-4 flex flex-col items-center gap-2.5 border-b border-line text-center">
            {!loopback(made.url) && (
              <div className="w-[220px] rounded-[14px] overflow-hidden [&_svg]:w-full [&_svg]:h-auto" aria-label="QR code for pairing" dangerouslySetInnerHTML={{ __html: made.svg }} />
            )}
            <div className="font-mono text-[24px] tracking-[0.18em] font-semibold" aria-label="Pairing code">{made.code}</div>
            <div className="text-[13px] leading-[19px] text-muted max-w-[300px]">
              {loopback(made.url)
                ? "Valid once, for 10 minutes. This browser has Odie open at this computer's own address, which another device can't reach: on the new device, open Odie at this computer's network address and type the code."
                : `Valid once, for 10 minutes. On the new device, scan the QR code with the camera, or open ${new URL(made.url).host} and type the code.`}
            </div>
            <button onClick={() => { setMade(null); load(); }} className="pill h-10 text-[14px] shadow-none">Done</button>
          </div>
        ) : (
          <button disabled={busy} onClick={addDevice} className="w-full flex items-center gap-3 px-4 py-3 min-h-14 border-b border-line text-left active:bg-well">
            <Tile icon="plus" color="blue" small />
            <span className="flex-1 text-[15px] font-medium">Add a device</span>
          </button>
        )}
        {passcode ? (
          <div className="px-4 py-4 flex flex-col gap-2 border-b border-line">
            <div className="text-[13px] text-muted">Your recovery passcode</div>
            <div className="font-mono text-[18px] font-semibold rounded-[12px] bg-well px-3 py-2.5 select-all">{passcode}</div>
            <div className="text-[12.5px] leading-[18px] text-muted">Write it down somewhere safe. It isn't shown again. Typed on a new device, it pairs that device.</div>
            <button onClick={() => setPasscode("")} className="pill h-10 text-[14px] shadow-none self-start">I wrote it down</button>
          </div>
        ) : (
          <button disabled={busy} onClick={newPasscode} className="w-full flex items-center gap-3 px-4 py-3 min-h-14 border-b border-line text-left active:bg-well">
            <Tile icon="spark" color="violet" small />
            <span className="flex-1 min-w-0">
              <b className="block text-[15px] font-medium">New recovery passcode</b>
              <span className={`block text-[13px] leading-[18px] ${needsPasscode(status) ? "text-warn-ink" : "text-muted"}`}>
                {needsPasscode(status) ? "None yet. Without one, losing your only paired device locks you out." : "Four words that pair a device when no other is at hand"}
              </span>
            </span>
          </button>
        )}
        {status?.on && (
          <button disabled={busy} onClick={() => turn(false)} className="w-full px-4 py-3 text-left text-[13.5px] text-muted active:bg-well">Turn off device pairing</button>
        )}
        {error && <div className="px-4 pb-3 pt-1 text-[13px] text-warn-ink">{error}</div>}
      </div>
    </section>
  );
}
