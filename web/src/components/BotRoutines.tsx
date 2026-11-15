import { useCallback, useEffect, useState } from "react";
import { getJSON } from "../api";
import { DAYS, nextWords, type Routine, type Schedule } from "../bots";
import { userLocale } from "../locale";

async function call(url: string, method: string, body?: unknown): Promise<{ ok: boolean; data: any }> {
  const r = await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
  return { ok: r.ok, data: await r.json().catch(() => ({})) };
}

/** Runs by itself (a bot's details): its routines, each with when it runs next, Pause/Resume, Run now and Delete, and
 * a form to add one: what to do, and daily at a time on chosen days, or every few hours. */
export function BotRoutines({ bot }: { bot: string }) {
  const [list, setList] = useState<Routine[] | null>(null);
  const [adding, setAdding] = useState(false);
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
            <span className="ml-auto text-[12px] text-muted shrink-0">{r.paused ? "paused" : `next ${nextWords(r.next_run_at, undefined, locale)}`}</span>
          </a>
          <div className="text-[12.5px] text-muted">{r.when} · {r.brief}</div>
          <div className="flex gap-2">
            <button onClick={() => void act(r, r.paused ? "resume" : "pause")} className="pill h-8 px-3 text-[12.5px]">{r.paused ? "Resume" : "Pause"}</button>
            <button onClick={() => void act(r, "run")} className="pill h-8 px-3 text-[12.5px]">Run now</button>
            <button onClick={() => void act(r, "delete")} className="pill h-8 px-3 text-[12.5px]">Delete</button>
          </div>
        </div>
      ))}
      {adding && <NewRoutine bot={bot} onDone={(made) => { setAdding(false); if (made) load(); }} />}
      {note && <div className="text-[13px] text-ember-text">{note}</div>}
    </div>
  );
}

function NewRoutine({ bot, onDone }: { bot: string; onDone: (made: boolean) => void }) {
  const [brief, setBrief] = useState("");
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState<"daily" | "every">("daily");
  const [at, setAt] = useState("08:30");
  const [days, setDays] = useState<number[]>([0, 1, 2, 3, 4, 5, 6]);
  const [hours, setHours] = useState(3);
  const [error, setError] = useState("");
  const toggle = (d: number) => setDays((now) => (now.includes(d) ? now.filter((x) => x !== d) : [...now, d].sort()));
  async function save() {
    setError("");
    const schedule: Schedule = kind === "daily" ? { kind, at, days } : { kind, hours };
    const got = await call(`/api/bots/${bot}/routines`, "POST", { title, brief, schedule });
    if (!got.ok) { setError(got.data.detail || "Couldn't save."); return; }
    onDone(true);
  }
  const field = "w-full rounded-[14px] border border-line-2 bg-transparent px-3 py-2 text-[14px]";
  return (
    <div className="rounded-[16px] border border-line-2 p-3 flex flex-col gap-2.5">
      <textarea value={brief} onChange={(e) => setBrief(e.target.value)} placeholder="What should it do each time? (Tell me what moved in my watchlist, and why.)" className={`${field} min-h-[72px]`} maxLength={2000} />
      <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="A short name (Morning market note)" className={field} maxLength={60} />
      <div className="p-1 rounded-full bg-well flex gap-1" role="radiogroup" aria-label="When">
        {(["daily", "every"] as const).map((k) => (
          <button key={k} role="radio" aria-checked={kind === k} onClick={() => setKind(k)}
            className={`flex-1 h-8 rounded-full text-[13px] font-semibold ${kind === k ? "glass-solid text-ink" : "text-muted"}`}>{k === "daily" ? "At a time" : "Every few hours"}</button>
        ))}
      </div>
      {kind === "daily" ? (
        <>
          <input type="time" value={at} onChange={(e) => setAt(e.target.value)} className={`${field} h-11`} />
          <div className="flex gap-1.5 flex-wrap">
            {DAYS.map((d, i) => (
              <button key={d} onClick={() => toggle(i)} aria-pressed={days.includes(i)}
                className={`h-8 px-2.5 rounded-full text-[12.5px] font-semibold border ${days.includes(i) ? "bg-ember text-on-ember border-transparent" : "border-line-2 text-muted"}`}>{d}</button>
            ))}
          </div>
        </>
      ) : (
        <label className="flex items-center gap-2 text-[14px]">Every
          <input type="number" min={1} max={168} value={hours} onChange={(e) => setHours(Number(e.target.value))} className="w-20 h-10 rounded-[12px] border border-line-2 bg-transparent px-2" />
          hours</label>
      )}
      {error && <div className="text-[13px] text-ember-text">{error}</div>}
      <div className="flex gap-2 justify-end">
        <button onClick={() => onDone(false)} className="pill h-10 px-4 text-[14px]">Cancel</button>
        <button disabled={!brief.trim()} onClick={() => void save()} className="h-10 px-4 rounded-[14px] bg-ember text-on-ember font-semibold text-[14px] disabled:opacity-50">Save</button>
      </div>
    </div>
  );
}
