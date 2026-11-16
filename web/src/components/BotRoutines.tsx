import { useCallback, useEffect, useState } from "react";
import { getJSON } from "../api";
import { routineState, nextWords, type Routine, type WhenPreview } from "../bots";
import { userLocale } from "../locale";

async function call(url: string, method: string, body?: unknown): Promise<{ ok: boolean; data: any }> {
  const r = await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
  return { ok: r.ok, data: await r.json().catch(() => ({})) };
}

/** Runs by itself (a bot's details): its routines, each with when it runs next, Pause/Resume, Run now, Edit and
 * Delete, and a form to add one: what to do, and when, in words ("weekdays at 9:15 and 6pm"). */
export function BotRoutines({ bot }: { bot: string }) {
  const [list, setList] = useState<Routine[] | null>(null);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const load = useCallback(() => { getJSON<{ routines: Routine[] }>(`/api/bots/${bot}/routines`).then((r) => setList(r.routines)).catch(() => setList([])); }, [bot]);
  useEffect(load, [load]);
  const locale = userLocale();

  async function act(r: Routine, what: "pause" | "resume" | "run" | "delete") {
    setNote("");
    const got = what === "run" ? await call(`/api/routines/${r.id}/run`, "POST")
      : what === "delete" ? (confirm(`Stop "${r.title}" for good? Its conversation stays.`) ? await call(`/api/routines/${r.id}`, "DELETE") : null)
      : await call(`/api/routines/${r.id}`, "PUT", { paused: what === "pause" });
    if (got && !got.ok) setNote(got.data.detail || "That didn't work.");
    if (got?.ok && what === "run") { location.hash = `#bot/${bot}/${r.conv_id}`; return; }
    load();
  }

  return (
    <div className="px-5 flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="text-[12.5px] text-muted">Runs by itself</span>
        {!adding && <button onClick={() => setAdding(true)} className="text-[13px] font-semibold text-ember-text">+ Add a routine</button>}
      </div>
      {list?.length === 0 && !adding && <div className="text-[13px] text-muted">Nothing yet. A routine runs on a schedule and answers in its own conversation, like "every weekday at 9:15, what moved in my stocks".</div>}
      {list?.map((r) => (
        <div key={r.id} className="rounded-[16px] bg-well px-3 py-2.5 flex flex-col gap-1.5">
          <a href={`#bot/${bot}/${r.conv_id}`} className="flex items-center gap-2">
            <span className="text-[14px] font-semibold truncate">{r.title}</span>
            <span className="ml-auto text-[12px] text-muted shrink-0">{routineState(r, undefined, locale)}</span>
          </a>
          <div className="text-[12.5px] text-muted">{r.when} · {r.brief}</div>
          <div className="flex gap-2">
            <button onClick={() => void act(r, r.paused ? "resume" : "pause")} className="pill h-8 px-3 text-[12.5px]">{r.paused ? "Resume" : "Pause"}</button>
            <button onClick={() => void act(r, "run")} className="pill h-8 px-3 text-[12.5px]">Run now</button>
            <button onClick={() => setEditing(r.id)} className="pill h-8 px-3 text-[12.5px]">Edit</button>
            <button onClick={() => void act(r, "delete")} className="pill h-8 px-3 text-[12.5px]">Delete</button>
          </div>
          {editing === r.id && <NewRoutine bot={bot} initial={r} onDone={(made) => { setEditing(null); if (made) load(); }} />}
        </div>
      ))}
      {adding && <NewRoutine bot={bot} onDone={(made) => { setAdding(false); if (made) load(); }} />}
      {note && <div className="text-[13px] text-ember-text">{note}</div>}
    </div>
  );
}

const EXAMPLES = ["Every day at 8", "Weekdays at 9:15 and 6pm", "Every 2 hours from 9 to 6", "1st of the month at 9", "Tomorrow 3pm"];

/** A routine's form: new, or `initial` to edit one (saved with PUT; the next run moves only if the timing changed).
 * When is said in words; under the box the server reads them back ("Weekdays at 09:15 and 18:00") with the next three
 * runs, or says what it didn't follow, before anything is saved. */
function NewRoutine({ bot, initial, onDone }: { bot: string; initial?: Routine; onDone: (made: boolean) => void }) {
  const [brief, setBrief] = useState(initial?.brief ?? "");
  const [title, setTitle] = useState(initial?.title ?? "");
  const [when, setWhen] = useState(initial?.when ?? "");
  const [preview, setPreview] = useState<WhenPreview | null>(null);
  const [error, setError] = useState("");
  const locale = userLocale();
  useEffect(() => {
    if (!when.trim()) { setPreview(null); return; }
    const timer = setTimeout(() => {
      void call("/api/routines/when", "POST", { text: when }).then((got) => setPreview(got.ok ? got.data : { error: "Couldn't check that." }));
    }, 350);
    return () => clearTimeout(timer);
  }, [when]);
  const understood = preview !== null && "words" in preview;
  async function save() {
    setError("");
    const sameWhen = initial && when.trim() === initial.when;
    const timing = sameWhen ? {} : { when };
    const got = initial
      ? await call(`/api/routines/${initial.id}`, "PUT", { title, brief, ...timing })
      : await call(`/api/bots/${bot}/routines`, "POST", { title, brief, when });
    if (!got.ok) { setError(got.data.detail || "Couldn't save."); return; }
    onDone(true);
  }
  const field = "w-full rounded-[14px] border border-line-2 bg-transparent px-3 py-2 text-[14px]";
  return (
    <div className="rounded-[16px] border border-line-2 p-3 flex flex-col gap-2.5">
      <textarea value={brief} onChange={(e) => setBrief(e.target.value)} placeholder="What should it do each time? (Tell me what moved in my watchlist, and why.)" className={`${field} min-h-[72px]`} maxLength={2000} />
      <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="A short name (Morning market note)" className={field} maxLength={60} />
      <label className="flex flex-col gap-1.5">
        <span className="text-[12.5px] text-muted">When</span>
        <input value={when} onChange={(e) => setWhen(e.target.value)} placeholder="Weekdays at 9:15 and 6pm" className={`${field} h-11`} maxLength={200} aria-describedby="when-preview" />
      </label>
      {!when.trim() && (
        <div className="flex gap-1.5 flex-wrap">
          {EXAMPLES.map((x) => (
            <button key={x} onClick={() => setWhen(x)} className="h-8 px-2.5 rounded-full text-[12.5px] border border-line-2 text-muted">{x}</button>
          ))}
        </div>
      )}
      <div id="when-preview" aria-live="polite" className="text-[12.5px]">
        {preview && "error" in preview && <span className="text-ember-text">{preview.error}</span>}
        {preview && "words" in preview && (
          <div className="flex flex-col gap-0.5">
            <span className="font-semibold">{preview.words}</span>
            <span className="text-muted">Next: {preview.next.map((iso) => nextWords(iso, undefined, locale)).join(" · ")}</span>
          </div>
        )}
      </div>
      {error && <div className="text-[13px] text-ember-text">{error}</div>}
      <div className="flex gap-2 justify-end">
        <button onClick={() => onDone(false)} className="pill h-10 px-4 text-[14px]">Cancel</button>
        <button disabled={!brief.trim() || !understood} onClick={() => void save()} className="h-10 px-4 rounded-[14px] bg-ember text-on-ember font-semibold text-[14px] disabled:opacity-50">Save</button>
      </div>
    </div>
  );
}
