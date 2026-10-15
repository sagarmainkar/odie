import { useEffect, useState } from "react";
import { checkForUpdate, checkedAgo, startUpdate, useUpdate } from "../update";
import { Tile } from "./Tile";
import { UpdateCurtain } from "./UpdateCurtain";

/** Settings → Odie: the version this Odie runs, whether a newer one is on origin, and the button that updates it.
 *  The hourly check itself lives in App (useUpdate there); this row shows its answer and can ask again. */
export function UpdateSection({ version }: { version: string | undefined }) {
  const u = useUpdate(false);
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 30000); return () => clearInterval(t); }, []);
  const [updating, setUpdating] = useState<{ from: string; to: string } | null>(null);
  const behind = !!u.info?.behind;
  const running = !!u.info?.running;

  async function update() {
    if (!u.info) return;
    if (!confirm(`Update Odie from ${u.info.current} to ${u.info.latest}? It fetches, builds and restarts: about a minute, and it rolls back on its own if the new version isn't healthy.`)) return;
    try {
      const r = await startUpdate();
      setUpdating({ from: r.from, to: u.info.latest });
    } catch (e) {
      alert(e instanceof Error ? e.message : "Couldn't start the update");
    }
  }

  // What the row says: a new version first, then a problem checking, then "up to date, checked 5 min ago".
  let sub: string;
  if (running) sub = "An update is running";
  else if (behind) sub = `A new version is ready: ${u.info?.latest}`;
  else if (u.error) sub = `Couldn't check: ${u.error}`;
  else if (u.checking && !u.info) sub = "Checking…";
  else sub = `Up to date · ${checkedAgo(u.checkedAt, now)}`;
  const dot = running || u.checking ? "bg-dim ring-surface-2" : behind ? "bg-gold ring-gold-tint" : u.error ? "bg-ember ring-ember-tint" : "bg-moss ring-moss-tint";

  return (
    <section className="flex flex-col gap-2">
      <div className="text-[13px] leading-5 font-bold text-muted px-1.5">Odie</div>
      <div className="glass rounded-[26px] overflow-hidden">
        <div className="flex items-center gap-3 px-4 py-3 min-h-14">
          <span className="relative shrink-0"><Tile icon="spark" color="ink" small /><span className="absolute -right-0.5 -bottom-0.5 rounded-full bg-[var(--t-surface-2)] p-[2px] flex"><span className={`w-2 h-2 rounded-full ring-2 shrink-0 ${dot}`} /></span></span>
          <div className="flex-1 min-w-0">
            <div className="text-[14.5px] font-medium">Odie{version ? ` · ${version}` : ""}</div>
            <div className="text-[12.5px] leading-[18px] text-muted">{sub}</div>
          </div>
          {behind && !running ? (
            <button type="button" onClick={() => void update()} className="h-10 px-4 rounded-[14px] bg-ember text-on-ember font-semibold text-[14px] shrink-0">Update Odie</button>
          ) : (
            <button type="button" onClick={() => void checkForUpdate(true)} disabled={u.checking || running} className="text-ember-text font-medium shrink-0 disabled:opacity-50">
              {u.checking ? "Checking…" : "Check now"}
            </button>
          )}
        </div>
      </div>
      {updating && <UpdateCurtain from={updating.from} to={updating.to} />}
    </section>
  );
}
