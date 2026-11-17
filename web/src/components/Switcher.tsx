import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useState } from "react";
import { usePersona, type Persona } from "../persona";
import { createPersonality, odieLine, rowLine, useElsewhere, usePersonalities } from "../personalities";
import { setPick, usePick } from "../pick";
import { Avatar } from "./Avatar";
import { Icon } from "./Tile";
import { ToBody } from "./ToBody";

function Row({ who, line, picked, waiting, onPick }: { who: Persona; line: string; picked: boolean; waiting: boolean; onPick: () => void }) {
  return (
    <button onClick={onPick} aria-current={picked ? "true" : undefined}
      className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-[18px] text-left ${picked ? "bg-well" : ""}`}>
      <Avatar size={44} who={who} />
      <span className="flex-1 min-w-0">
        <b className="block text-[16px] font-semibold truncate">{who.name}</b>
        <span className={`block text-[13px] truncate ${waiting ? "text-ember-text font-semibold" : "text-muted"}`}>{line}</span>
      </span>
      {picked && <span className="text-ember-text shrink-0" aria-hidden="true"><Icon name="check" size={18} /></span>}
    </button>
  );
}

/** "Who are you talking to?": everyday Odie and every personality. Picking one switches the chat, its threads and
 *  Settings to it. "New personality" asks for a name only; it starts with the orb and the default instructions, which
 *  Settings then changes. */
export function Switcher({ open, onClose }: { open: boolean; onClose: () => void }) {
  const pick = usePick();
  const odie = usePersona();
  const { list, everydayWaiting, reload } = usePersonalities();
  const seen = useElsewhere();
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");
  const [problem, setProblem] = useState("");
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    if (!open) return;
    reload();
    setNaming(false); setName(""); setProblem("");
  }, [open, reload]);

  function choose(id: string) { setPick(id); onClose(); }

  async function make() {
    if (saving) return;
    setSaving(true); setProblem("");
    try {
      const made = await createPersonality(name);
      choose(made.id);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That didn't work. Try again.");  // the server's own words for a name it won't take
    } finally { setSaving(false); }
  }

  const odieNote = pick === "" ? undefined : seen[""];
  const odieCards = pick === "" ? 0 : everydayWaiting;  // while someone else is on screen, Odie's waiting cards count
  return (
    <ToBody>
      <AnimatePresence>
        {open && (
          <>
            <motion.div key="scrim" className="fixed inset-0 z-40 bg-black/30" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} />
            <motion.div key="sheet" role="dialog" aria-label="Who are you talking to?"
              className="fixed z-50 left-0 right-0 bottom-0 mx-auto w-full max-w-[460px] max-h-[82dvh] flex flex-col bg-ground border border-line rounded-t-[28px] shadow-2xl safe-bottom"
              initial={{ y: "100%" }} animate={{ y: 0 }} exit={{ y: "100%" }} transition={{ duration: 0.28, ease: [0.2, 0.8, 0.2, 1] }}>
              <div className="px-5 pt-5 pb-3 flex items-center gap-2">
                <div className="text-[20px] font-bold tracking-[-0.015em] flex-1">Who are you talking to?</div>
                <button onClick={onClose} aria-label="Close" className="pill w-10 h-10 px-0"><Icon name="x" size={16} /></button>
              </div>
              <div className="flex-1 overflow-y-auto no-scrollbar px-2 pb-2">
                <Row who={odie} line={odieLine(odieNote, odieCards)} picked={pick === ""} waiting={odieNote !== undefined || odieCards > 0} onPick={() => choose("")} />
                {list.map((p) => {
                  const note = p.id === pick ? undefined : seen[p.id];
                  const line = rowLine(p, note);
                  return <Row key={p.id} who={{ name: p.name, avatar_url: p.avatar_url }} line={line} picked={p.id === pick}
                    waiting={line === "needs you" || line === "new"} onPick={() => choose(p.id)} />;
                })}
              </div>
              <div className="px-4 pt-2 pb-2 border-t border-line">
                {!naming ? (
                  <button onClick={() => setNaming(true)} className="w-full flex items-center gap-3 px-1 py-2.5 text-left text-[15.5px] font-semibold">
                    <span className="w-11 h-11 rounded-full grid place-items-center bg-well text-ink-2"><Icon name="plus" size={18} /></span>
                    New personality
                  </button>
                ) : (
                  <form onSubmit={(e) => { e.preventDefault(); void make(); }} className="py-1.5">
                    <label className="sr-only" htmlFor="new-personality-name">Its name</label>
                    <div className="flex items-center gap-2">
                      <input id="new-personality-name" value={name} maxLength={24} autoFocus onChange={(e) => { setName(e.target.value); setProblem(""); }}
                        placeholder="Its name" autoComplete="off"
                        className="flex-1 min-w-0 h-12 px-3.5 rounded-[14px] bg-well border border-line outline-none text-[16px] focus:border-line-2" />
                      <button type="submit" disabled={saving || !name.trim()} className="pill pill-solid h-12 text-[14.5px] shadow-none disabled:opacity-50">{saving ? "Making…" : "Make"}</button>
                    </div>
                    <p className={`mt-2 px-1 text-[13px] ${problem ? "text-ember-text" : "text-muted"}`} role={problem ? "alert" : undefined}>
                      {problem || "It starts with the orb and Odie's default way of talking. Change its picture and instructions in Settings."}
                    </p>
                  </form>
                )}
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </ToBody>
  );
}
