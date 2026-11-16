import { useEffect, useState } from "react";
import { getJSON } from "../api";
import { modelChoices, whenWords, type Bot } from "../bots";
import { BotEditor } from "./BotsSection";
import { BotActivity } from "./BotActivity";
import { BotRoutines } from "./BotRoutines";
import { Creature } from "./Creature";

type Providers = { id: string; name: string; models: { id: string }[]; error: string | null }[];

/** A bot's details (Fable's design, frame E), from the name in its chat's header: its creature, role, model,
 * instructions, powers, what it remembers (folded: a count, opened to read or edit), and Delete. Saving makes the
 * bot yours. */
export function BotDetails({ bot, onClose }: { bot: Bot; onClose: (changed: boolean) => void }) {
  const [look, setLook] = useState(bot.look);
  const [shuffled, setShuffled] = useState(false);
  const [powers, setPowers] = useState<string[]>([]);
  const [providers, setProviders] = useState<Providers>([]);
  const [memory, setMemory] = useState<Memory | null>(null);
  useEffect(() => {
    getJSON<{ powers: string[] }>("/api/bots").then((r) => setPowers(r.powers)).catch(() => {});
    getJSON<{ providers: Providers }>("/api/models").then((r) => setProviders(r.providers)).catch(() => {});
    getJSON<Memory>(`/api/bots/${bot.name}/notes`).then(setMemory).catch(() => setMemory({ text: "", things: 0, updated_at: null }));
  }, [bot.name]);
  async function remove() {
    if (!confirm(`Delete ${bot.name}? Its routines stop; its conversations, folder and record stay.`)) return;
    const r = await fetch(`/api/bots/${bot.name}`, { method: "DELETE" });
    if (r.ok) { location.hash = "#bots"; onClose(true); }
  }

  async function shuffle() {
    const r = await fetch(`/api/bots/${bot.name}/look`, { method: "POST" });
    if (!r.ok) return;
    setLook(((await r.json()) as { look: Bot["look"] }).look);
    setShuffled(true);
  }
  const made = bot.chief ? "Always here" : bot.made_by === "odie" ? "One of Odie's starter team" : bot.made_by === "chief" ? "Made by the chief" : "Made by you";
  return (
    <div className="fixed inset-0 z-50 flex items-end lg:items-center justify-center bg-overlay" onClick={() => onClose(shuffled)}>
      <div className="glass glass-solid w-full max-w-[560px] max-h-[88vh] overflow-y-auto rounded-t-[28px] lg:rounded-[28px] pt-5 flex flex-col gap-2" onClick={(e) => e.stopPropagation()}>
        <div className="px-5 flex items-center gap-3">
          <Creature look={look} size={56} />
          <div className="min-w-0">
            <div className="text-[20px] font-bold">{bot.name}</div>
            <div className="text-[12.5px] text-muted">{made}{bot.edited_by_user ? " · edited by you" : ""}</div>
            {!bot.chief && <button onClick={() => void shuffle()} className="text-[12.5px] font-semibold text-ember-text">Shuffle look</button>}
          </div>
          <button onClick={() => onClose(shuffled)} className="ml-auto pill h-10 px-3 text-[13px]">Close</button>
        </div>
        <Section title="Who it is, and what it may use">
          <BotEditor bot={bot} powers={powers} choices={modelChoices(providers, bot.model)} onDone={() => onClose(true)} deleteHere={false} />
        </Section>
        <Section title=""><BotRoutines bot={bot.name} /></Section>
        <Section title=""><BotActivity bot={bot.name} /></Section>
        <Section title=""><Remembers bot={bot.name} memory={memory} onSaved={setMemory} /></Section>
        {!bot.chief && (
          <div className="px-5 pb-6 pt-2 border-t border-line">
            <button onClick={() => void remove()} className="text-[13.5px] text-ember-text font-semibold">Delete this bot</button>
            <div className="text-[12px] text-muted">Its routines stop. Its conversations, folder and record stay.</div>
          </div>
        )}
      </div>
    </div>
  );
}

/** One part of the details sheet, set apart from the next. */
function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border-t border-line pt-3 pb-1">
      {title && <div className="px-5 pb-1 text-[12px] font-semibold text-muted uppercase tracking-wide">{title}</div>}
      {children}
    </div>
  );
}

type Memory = { text: string; things: number; updated_at: string | null };

/** What a bot remembers between conversations (its notes.md), folded to one line: "Remembers 12 things · updated
 * today". Open it to read it, and Edit to fix or remove something; Save writes the notes whole. */
function Remembers({ bot, memory, onSaved }: { bot: string; memory: Memory | null; onSaved: (m: Memory) => void }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<string | null>(null);
  const [note, setNote] = useState("");
  if (memory === null) return null;
  const summary = memory.things === 0 ? "Remembers nothing yet"
    : `Remembers ${memory.things} thing${memory.things === 1 ? "" : "s"}${memory.updated_at ? ` · updated ${whenWords(memory.updated_at).toLowerCase()}` : ""}`;
  async function save() {
    setNote("");
    const r = await fetch(`/api/bots/${bot}/notes`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: draft ?? "" }) });
    if (!r.ok) { setNote("Couldn't save."); return; }
    onSaved((await r.json()) as Memory);
    setDraft(null);
  }
  return (
    <div className="px-5 pb-3 flex flex-col gap-2">
      <button onClick={() => setOpen(!open)} aria-expanded={open} className="flex items-center gap-2 text-left">
        <span className="text-[14px] font-semibold">{summary}</span>
        <span className="ml-auto text-[12.5px] text-muted">{open ? "Hide" : "Show"}</span>
      </button>
      {open && draft === null && (
        <>
          <div className="rounded-[14px] bg-well px-3 py-2.5 text-[13px] whitespace-pre-wrap max-h-[260px] overflow-y-auto">{memory.text || "Nothing yet. It writes down what a later conversation should know."}</div>
          <button onClick={() => setDraft(memory.text)} className="self-start pill h-8 px-3 text-[12.5px]">Edit</button>
        </>
      )}
      {open && draft !== null && (
        <>
          <textarea value={draft} onChange={(e) => setDraft(e.target.value)} maxLength={20000}
            className="w-full min-h-[200px] rounded-[14px] border border-line-2 bg-transparent px-3 py-2 text-[13px] font-mono" />
          <div className="flex gap-2 justify-end">
            <button onClick={() => setDraft(null)} className="pill h-9 px-3 text-[13px]">Cancel</button>
            <button onClick={() => void save()} className="h-9 px-3 rounded-[12px] bg-ember text-on-ember font-semibold text-[13px]">Save</button>
          </div>
        </>
      )}
      {note && <div className="text-[12.5px] text-ember-text">{note}</div>}
    </div>
  );
}
