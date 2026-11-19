import { useEffect, useState } from "react";
import { getJSON, postJSON, putJSON } from "../api";
import { usePick } from "../pick";
import { canAdd, cleanLines, LINE_MOST, moveLine, saveReady, withoutLine, type NowGot } from "../now";

/** What the editor opens with when Odie's proposal card's Edit was tapped: its lines, and its number so saving
 *  answers it. */
export type NowEdit = { lines: string[]; proposal: number };

/** Pulse's "Now": five to seven lines of what matters to the user now (the picked one's own list), which Odie reads to
 *  judge what needs him. Shown as a short numbered list with Edit; edited in place (reword, add, remove, move up or
 *  down, Save). With none yet: "Draft it for me" (Odie writes a first draft from what it remembers and the week; nothing
 *  is saved until Save) or "Write it". `editWith` opens the editor with Odie's proposed lines (its card's Edit).
 *  `initial`: the list as already read (tests); `onSaved`: after a save, so Pulse re-reads its cards; `onClosed`: the
 *  editor closed (saved or cancelled), so the same card's Edit can open it again. Pulse gives it a new key for each
 *  pick and each Edit, so it starts afresh. */
export function NowList({ who, initial, editWith, onSaved, onClosed }: {
  who: string; initial?: NowGot; editWith?: NowEdit | null; onSaved?: () => void; onClosed?: () => void;
}) {
  const pick = usePick();
  const [got, setGot] = useState<NowGot | null>(initial ?? null);
  const [editing, setEditing] = useState<string[] | null>(editWith ? editWith.lines : null);
  const [answering, setAnswering] = useState<number | null>(editWith ? editWith.proposal : null);
  const [busy, setBusy] = useState<"" | "draft" | "save">("");
  const [error, setError] = useState("");
  useEffect(() => {
    if (initial) return;
    getJSON<NowGot>("/api/now").then(setGot).catch(() => setGot({ lines: [], proposal: null, most: 7 }));
  }, [pick, initial]);
  if (!got) return null;
  const most = got.most;

  async function draft() {
    setBusy("draft");
    setError("");
    try {
      const d = await postJSON<{ lines: string[] }>("/api/now/draft", {});
      setEditing(d.lines.length ? d.lines : [""]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy("");
    }
  }
  async function save() {
    if (!editing || !saveReady(editing, most)) return;
    setBusy("save");
    setError("");
    try {
      const body: { lines: string[]; proposal?: number } = { lines: cleanLines(editing) };
      if (answering !== null) body.proposal = answering;
      const saved = await putJSON<{ lines: string[] }>("/api/now", body);
      setGot({ ...got!, lines: saved.lines });
      setEditing(null);
      setAnswering(null);
      onSaved?.();
      onClosed?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy("");
    }
  }
  function cancel() {
    setEditing(null);
    setAnswering(null);
    setError("");
    onClosed?.();
  }
  const setLine = (i: number, text: string) => setEditing((ls) => (ls ?? []).map((l, k) => (k === i ? text : l)));

  return (
    <section className="flex flex-col gap-2.5" aria-label="Now">
      <div className="section-head flex items-baseline gap-2 px-1">
        <div className="text-heading font-bold tracking-[-0.015em]">Now</div>
        <div className="text-caption text-dim flex-1 truncate">what matters to you this month</div>
        {editing === null && got.lines.length > 0 && (
          <button type="button" onClick={() => { setEditing(got.lines); setError(""); }}
            className="text-small font-semibold text-ember-text underline underline-offset-2">Edit</button>
        )}
      </div>
      {editing === null && got.lines.length > 0 && (
        <ol className="glass rounded-card px-4 py-2">
          {got.lines.map((line, i) => (
            <li key={i} className={`flex gap-3 py-2 ${i ? "border-t border-line" : ""}`}>
              <span className="serif text-title leading-[22px] text-dim w-4 shrink-0 tabular-nums" aria-hidden="true">{i + 1}</span>
              <span className="flex-1 min-w-0 text-body leading-[22px] text-ink-2 break-words">{line}</span>
            </li>
          ))}
        </ol>
      )}
      {editing === null && got.lines.length === 0 && (
        <div className="glass rounded-card px-4 py-3.5 flex flex-col gap-3">
          <div className="text-ui text-muted">A few lines on what matters to you now help {who} judge what needs you, and what can wait.</div>
          <div className="flex gap-2 flex-wrap">
            <button type="button" onClick={() => void draft()} disabled={busy !== ""}
              className="pill pill-solid h-9 px-4 text-ui shadow-none disabled:opacity-60">{busy === "draft" ? "Drafting…" : "Draft it for me"}</button>
            <button type="button" onClick={() => setEditing([""])} disabled={busy !== ""} className="pill h-9 px-3 text-ui disabled:opacity-60">Write it</button>
          </div>
        </div>
      )}
      {editing !== null && (
        <div className="glass glass-solid rounded-card px-3 py-3 flex flex-col gap-2" aria-label="Edit your Now list">
          {answering !== null && <div className="text-small text-muted px-1">{who}'s proposal: change what you like, then save.</div>}
          {editing.map((line, i) => (
            <div key={i} className="flex items-center gap-1">
              <span className="serif text-title text-dim w-3.5 shrink-0 text-center tabular-nums" aria-hidden="true">{i + 1}</span>
              <input value={line} onChange={(e) => setLine(i, e.target.value)} maxLength={LINE_MOST} aria-label={`Line ${i + 1}`}
                placeholder="Something that matters now" className="flex-1 min-w-0 h-10 rounded-tile bg-well px-3 text-ui text-ink outline-none focus:ring-2 focus:ring-brand" />
              <button type="button" onClick={() => setEditing(moveLine(editing, i, -1))} disabled={i === 0} aria-label={`Move line ${i + 1} up`}
                className="h-9 w-7 shrink-0 grid place-items-center rounded-full text-ui text-muted active:bg-well disabled:opacity-30">↑</button>
              <button type="button" onClick={() => setEditing(moveLine(editing, i, 1))} disabled={i === editing.length - 1} aria-label={`Move line ${i + 1} down`}
                className="h-9 w-7 shrink-0 grid place-items-center rounded-full text-ui text-muted active:bg-well disabled:opacity-30">↓</button>
              <button type="button" onClick={() => setEditing(withoutLine(editing, i))} aria-label={`Remove line ${i + 1}`}
                className="h-9 w-7 shrink-0 grid place-items-center rounded-full text-ui text-muted active:bg-well">×</button>
            </div>
          ))}
          <button type="button" onClick={() => setEditing([...editing, ""])} disabled={!canAdd(editing, most)}
            className="self-start text-small font-semibold text-ember-text underline underline-offset-2 px-1 disabled:opacity-50 disabled:no-underline">
            {canAdd(editing, most) ? "+ Add a line" : `${most} lines is the most`}
          </button>
          {error && <div role="alert" className="text-small text-warn-ink px-1">{error}</div>}
          <div className="flex gap-2 pt-1">
            <button type="button" onClick={() => void save()} disabled={busy !== "" || !saveReady(editing, most)}
              className="pill pill-solid h-9 px-4 text-ui shadow-none disabled:opacity-60">{busy === "save" ? "Saving…" : "Save"}</button>
            <button type="button" onClick={cancel} disabled={busy !== ""} className="pill h-9 px-3 text-ui">Cancel</button>
          </div>
        </div>
      )}
      {editing === null && error && <div role="alert" className="text-small text-warn-ink px-1">{error}</div>}
    </section>
  );
}
