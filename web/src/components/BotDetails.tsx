import { useEffect, useState } from "react";
import { getJSON } from "../api";
import { modelChoices, type Bot } from "../bots";
import { BotEditor } from "./BotsSection";
import { BotActivity } from "./BotActivity";
import { BotRoutines } from "./BotRoutines";
import { Creature } from "./Creature";

type Providers = { id: string; name: string; models: { id: string }[]; error: string | null }[];

/** A bot's details (Fable's design, frame E), from the name in its chat's header: its creature, role, model,
 * instructions, powers, its memory notes, and Delete. Saving makes the bot yours. */
export function BotDetails({ bot, onClose }: { bot: Bot; onClose: (changed: boolean) => void }) {
  const [look, setLook] = useState(bot.look);
  const [shuffled, setShuffled] = useState(false);
  const [powers, setPowers] = useState<string[]>([]);
  const [providers, setProviders] = useState<Providers>([]);
  const [notes, setNotes] = useState<string | null>(null);
  useEffect(() => {
    getJSON<{ powers: string[] }>("/api/bots").then((r) => setPowers(r.powers)).catch(() => {});
    getJSON<{ providers: Providers }>("/api/models").then((r) => setProviders(r.providers)).catch(() => {});
    getJSON<{ text: string }>(`/api/bots/${bot.name}/notes`).then((r) => setNotes(r.text)).catch(() => setNotes(""));
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
        <div className="px-5 pb-3 flex flex-col gap-1.5">
          <div className="text-[12.5px] text-muted">Memory notes (its notes.md: what it keeps between conversations)</div>
          <div className="rounded-[14px] bg-well px-3 py-2.5 text-[13px] whitespace-pre-wrap max-h-[220px] overflow-y-auto">{notes === null ? "…" : notes || "Nothing yet."}</div>
        </div>
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
