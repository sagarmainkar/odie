import { useCallback, useEffect, useState } from "react";
import { getPick, onPickChange, setPick, settlePick } from "./pick";

/** A personality as the switcher shows it. `waiting`: its cards waiting for a tap. */
export type Personality = { id: string; name: string; avatar_url: string | null; threads: number; waiting: number };

/** What the live stream said is waiting in a personality that isn't on screen: no words, only that. */
export type Elsewhere = Record<string, "reply" | "card">;

const LIST_CHANGED = "odie:personalities";
const NOTES_CHANGED = "odie:elsewhere";
let notes: Elsewhere = {};

/** The line under a personality's name in the switcher: a waiting card first, then a new reply, else its threads.
 *    waiting 1 -> "needs you";  note "reply" -> "new";  4 threads -> "4 threads";  none -> "No threads yet". */
export function rowLine(p: Personality, note: "reply" | "card" | undefined): string {
  if (p.waiting > 0 || note === "card") return "needs you";
  if (note === "reply") return "new";
  if (p.threads === 0) return "No threads yet";
  return p.threads === 1 ? "1 thread" : `${p.threads} threads`;
}

/** The line under everyday Odie's name in the switcher: what waits there while someone else is on screen, else
 *  "everyday":  "card" -> "needs you";  "reply" -> "new";  nothing -> "everyday". */
export function odieLine(note: "reply" | "card" | undefined): string {
  if (note === "card") return "needs you";
  if (note === "reply") return "new";
  return "everyday";
}

/** Whether the chat's header shows its dot: someone who isn't on screen has a card or a new reply. That is a
 *  personality other than the picked one, or everyday Odie (noted under "") while a personality is picked. */
export function somethingElsewhere(list: Personality[], seen: Elsewhere, pick: string): boolean {
  const odieWaits = pick !== "" && seen[""] !== undefined;
  return odieWaits || list.some((p) => p.id !== pick && (p.waiting > 0 || seen[p.id] !== undefined));
}

/** The live stream's "elsewhere" notice: something waits in this personality. */
export function noteElsewhere(id: string, what: "reply" | "card"): void {
  if (notes[id] === "card" && what === "reply") return;  // a card stays the more pressing line
  notes = { ...notes, [id]: what };
  window.dispatchEvent(new Event(NOTES_CHANGED));
}

/** The user switched to it: what was waiting there is on screen now. */
export function clearElsewhere(id: string): void {
  if (notes[id] === undefined) return;
  const rest = { ...notes };
  delete rest[id];
  notes = rest;
  window.dispatchEvent(new Event(NOTES_CHANGED));
}

export function useElsewhere(): Elsewhere {
  const [seen, setSeen] = useState(notes);
  useEffect(() => {
    const read = () => setSeen(notes);
    window.addEventListener(NOTES_CHANGED, read);
    return () => window.removeEventListener(NOTES_CHANGED, read);
  }, []);
  return seen;
}

export function personalitiesChanged(): void { window.dispatchEvent(new Event(LIST_CHANGED)); }

/** Every personality, for the switcher. It loads at the start, after one is made, renamed or deleted, when the pick
 *  changes and when a card starts waiting somewhere; a pick whose personality is gone falls back to everyday Odie. */
export function usePersonalities(): { list: Personality[]; reload: () => void } {
  const [list, setList] = useState<Personality[]>([]);
  const reload = useCallback(() => {
    fetch("/api/personalities").then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d: { personalities: Personality[] }) => {
        setList(d.personalities);
        const kept = settlePick(getPick(), d.personalities.map((p) => p.id));
        if (kept !== getPick()) setPick(kept);
      }).catch(() => { /* an older server, or offline: no personalities to show */ });
  }, []);
  useEffect(() => {
    reload();
    window.addEventListener(LIST_CHANGED, reload);
    window.addEventListener(NOTES_CHANGED, reload);
    const stop = onPickChange(reload);
    return () => { window.removeEventListener(LIST_CHANGED, reload); window.removeEventListener(NOTES_CHANGED, reload); stop(); };
  }, [reload]);
  return { list, reload };
}

/** Make a personality. A name the server won't take throws its own words ("You already have one called Mira."). */
export async function createPersonality(name: string): Promise<Personality> {
  const r = await fetch("/api/personalities", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }) });
  if (!r.ok) {
    const said = await r.json().catch(() => ({}));
    throw new Error(typeof said.detail === "string" ? said.detail : "That didn't work. Try again.");
  }
  const made = (await r.json()) as Personality;
  personalitiesChanged();
  return made;
}

/** Erase a personality for good. Returns how many threads went with it. */
export async function deletePersonality(id: string): Promise<{ threads: number }> {
  const r = await fetch(`/api/personalities/${id}`, { method: "DELETE" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  const gone = (await r.json()) as { threads: number };
  personalitiesChanged();
  return gone;
}
