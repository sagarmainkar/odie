import { useEffect, useState } from "react";
import { deleteJSON, getJSON, postJSON } from "../api";
import { learnedLine, quietShows, type QuietGot } from "../digest";
import { usePick } from "../pick";
import { pulseTaps } from "../tapGuard";

/** Pulse's "Quiet": what goes to the evening digest instead of cards. His rules (written by his tap on "Less like
 *  this", or Add the rule on Odie's proposal), each in plain words with × to delete; and the kinds Odie learned he
 *  rarely acts on, each with Undo. Nothing shows until there is one. `initial`: as already read (tests); `reload`:
 *  bumped when a rule was just added elsewhere, so it reads again. */
export function QuietList({ initial, reload = 0 }: { initial?: QuietGot; reload?: number }) {
  const pick = usePick();
  const [got, setGot] = useState<QuietGot | null>(initial ?? null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (initial) return;
    getJSON<QuietGot>("/api/quiet").then(setGot).catch(() => setGot(null));
  }, [pick, initial, reload]);
  if (!got || !quietShows(got)) return null;
  const g = got;

  async function remove(id: number) {
    if (!pulseTaps.ok()) return;
    setError("");
    try {
      await deleteJSON(`/api/quiet/${id}`);
      setGot({ ...g, rules: g.rules.filter((r) => r.id !== id) });
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }
  async function undo(id: number) {
    if (!pulseTaps.ok()) return;
    setError("");
    try {
      await postJSON(`/api/learned/${id}/undo`, {});
      setGot({ ...g, learned: g.learned.filter((l) => l.id !== id) });
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }
  return (
    <section className="flex flex-col gap-2.5" aria-label="Quiet">
      <div className="flex items-baseline gap-2 px-1">
        <div className="text-heading font-bold tracking-[-0.015em]">Quiet</div>
        <div className="text-caption text-dim flex-1 truncate">in the evening digest, not cards</div>
      </div>
      <ul className="glass rounded-card px-4 py-1">
        {g.rules.map((r, i) => (
          <li key={`r${r.id}`} className={`flex items-center gap-3 py-2.5 ${i ? "border-t border-line" : ""}`}>
            <span className="flex-1 min-w-0 text-ui leading-[20px] text-ink-2 break-words">{r.text}</span>
            <button type="button" onClick={() => void remove(r.id)} aria-label={`Delete: ${r.text}`}
              className="h-8 w-8 shrink-0 grid place-items-center rounded-full text-ui text-muted active:bg-well">×</button>
          </li>
        ))}
        {g.learned.map((l, i) => (
          <li key={`l${l.id}`} className={`flex items-center gap-3 py-2.5 ${i || g.rules.length ? "border-t border-line" : ""}`}>
            <span className="flex-1 min-w-0 text-ui leading-[20px] text-ink-2 break-words">{learnedLine(l)}</span>
            <button type="button" onClick={() => void undo(l.id)} className="pill h-8 px-3 text-small shrink-0">Undo</button>
          </li>
        ))}
      </ul>
      {error && <div role="alert" className="text-small text-warn-ink px-1">{error}</div>}
    </section>
  );
}
