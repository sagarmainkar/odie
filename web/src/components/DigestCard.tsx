import { useCallback, useEffect, useState } from "react";
import { getJSON, postJSON } from "../api";
import { digestShows, type Digest } from "../digest";
import { getPick, usePick } from "../pick";
import { stillPicked } from "../pulse";
import { pulseTaps } from "../tapGuard";
import { Tile } from "./Tile";

/** The digest at the top of Pulse (proactive design §8): "This evening" (the 19:30 digest, until Got it) or "While you
 *  were away" (after 3+ hours away, when something happened). Its words; the cards that are digest lines instead (a
 *  kind he quieted or rarely acts on), each with Done; what was held back from his phone; and what the evening review
 *  changed, each with Undo. Opening it notes the visit (POST /api/digest/seen), so "away" counts from now; it asks
 *  again when the app comes back into view. `initial`: the digest as already read (tests); `onChanged`: after a Done
 *  or an Undo, so Pulse re-reads its cards. */
export function DigestCard({ initial, onChanged }: { initial?: Digest | null; onChanged?: () => void }) {
  const pick = usePick();
  const [got, setGot] = useState<Digest | null>(initial ?? null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const read = useCallback(() => {
    const askedFor = getPick();
    getJSON<{ digest: Digest | null }>("/api/digest").then((r) => {
      if (!stillPicked(askedFor, getPick())) return;
      setGot(r.digest);
      void postJSON("/api/digest/seen", {}).catch(() => {});
    }).catch(() => {});
  }, []);
  useEffect(() => {
    if (initial !== undefined) return;
    read();
    const back = () => { if (document.visibilityState === "visible") read(); };
    document.addEventListener("visibilitychange", back);
    return () => document.removeEventListener("visibilitychange", back);
  }, [pick, initial, read]);
  if (!got || !digestShows(got)) return null;
  const d = got;

  async function run(key: string, call: () => Promise<unknown>, after: (d: Digest) => Digest) {
    if (!pulseTaps.ok() || busy) return;
    setBusy(key);
    setError("");
    try {
      await call();
      setGot(after(d));
      onChanged?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy("");
    }
  }
  const gotIt = () => {
    setGot(null);
    if (d.kind === "evening") void postJSON("/api/digest/seen", { dismiss: true }).catch(() => {});
  };
  return (
    <section className="glass rounded-card px-4 py-3.5 flex flex-col gap-2.5" aria-label={d.title}>
      <div className="flex items-start gap-3">
        <Tile icon="spark" color="violet" small />
        <div className="flex-1 min-w-0">
          <div className="text-ui font-bold text-ink-2">{d.title}</div>
          {d.text && <p className="text-body leading-[1.5] text-ink-2 mt-0.5 break-words">{d.text}</p>}
        </div>
      </div>
      {d.quiet.length > 0 && (
        <div className="min-[430px]:ml-12 flex flex-col gap-1" aria-label="In the digest instead of cards">
          <div className="text-tiny font-bold uppercase tracking-[.07em] text-muted">In the digest instead of cards</div>
          {d.quiet.map((q) => (
            <div key={q.id} className="flex items-center gap-2 text-small leading-[18px] text-ink-2">
              <span className="flex-1 min-w-0 break-words">{q.title}</span>
              <button type="button" disabled={!!busy} onClick={() => void run(`q${q.id}`, () => postJSON(`/api/loops/${q.id}/done`, {}),
                (x) => ({ ...x, quiet: x.quiet.filter((y) => y.id !== q.id) }))} className="pill h-7 px-2.5 text-small shrink-0 disabled:opacity-60">
                {busy === `q${q.id}` ? "…" : "Done"}</button>
            </div>
          ))}
        </div>
      )}
      {d.held.length > 0 && (
        <div className="min-[430px]:ml-12 text-small leading-[18px] text-muted break-words">Held back from your phone: {d.held.join(", ")}</div>
      )}
      {d.changes.length > 0 && (
        <div className="min-[430px]:ml-12 flex flex-col gap-1" aria-label="The evening review changed">
          <div className="text-tiny font-bold uppercase tracking-[.07em] text-muted">Odie tidied up</div>
          {d.changes.map((c) => (
            <div key={c.id} className="flex items-center gap-2 text-small leading-[18px] text-ink-2">
              <span className="flex-1 min-w-0 break-words">{c.words}</span>
              <button type="button" disabled={!!busy} onClick={() => void run(`c${c.id}`, () => postJSON(`/api/review/${c.id}/undo`, {}),
                (x) => ({ ...x, changes: x.changes.filter((y) => y.id !== c.id) }))} className="pill h-7 px-2.5 text-small shrink-0 disabled:opacity-60">
                {busy === `c${c.id}` ? "…" : "Undo"}</button>
            </div>
          ))}
        </div>
      )}
      {error && <div role="alert" className="min-[430px]:ml-12 text-small text-warn-ink">{error}</div>}
      <div className="flex min-[430px]:pl-12">
        <button type="button" onClick={gotIt} className="pill h-8 px-3 text-small">Got it</button>
      </div>
    </section>
  );
}
