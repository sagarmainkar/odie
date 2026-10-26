// Where a drawn fence lives, so its blocks know where to save what the user does to them (a checklist's ticks).
// Chat provides the reply; each fence in it adds which fence it is. The gallery provides nothing: ticks stay local.
import { createContext, useContext, useEffect, useRef, useState } from "react";
import { answeredState, readSavedAnswer, type Answered, type FormValues } from "./formAnswer";
import type { FormBlock } from "./parse/form";
import { loadReply, readTicks, saveSoon, ticksAfterLoad, toggleTick, type Reply } from "./savedState";

/** The chat reply being drawn: its session and key (both missing for a reply the server hasn't named), its text,
 *  whether it is still streaming in (a diagram waits for the whole reply), and the form answers the user's messages
 *  after it carry, by form id (a form whose saved answer is missing finds it there). */
export type ReplyInfo = { sessionId?: string; messageKey?: string; text: string; streaming?: boolean; answers?: Record<string, FormValues> };
export const ReplyPlace = createContext<ReplyInfo | null>(null);

/** Where one fence's blocks save: its reply (null: don't save) and which fence of the reply it is, from 0. */
type Fence = { reply: Reply | null; fence: number };
export const FencePlace = createContext<Fence>({ reply: null, fence: 0 });

/**
 * Which fence of a reply starts at `offset` in its text: the number of ```odie-blocks fences that start before it.
 *   "Intro\n```odie-blocks\n[…]\n```\nMore\n```odie-blocks\n[…]\n```", at the second fence's offset → 1
 */
export function fenceNumber(text: string, offset: number): number {
  let before = 0;
  for (const m of text.matchAll(/^[ \t>]*```odie-blocks/gm)) {
    const fenceStart = m.index + m[0].indexOf("```");
    if (fenceStart < offset) before += 1;
  }
  return before;
}

/**
 * A checklist's ticks, saved with its reply. `path`: the checklist's place in its fence ("2"); `starting`: the ticks
 * the model gave; `count`: how many items it has. Returns the ticks to show and what a tap on item i does.
 * In a reply the server has named, saved ticks load when it is drawn and each tap is saved a moment later. Anywhere
 * else (the gallery, a reply still unnamed) ticks live on screen only.
 */
export function useSavedTicks(path: string, starting: number[], count: number): [number[], (i: number) => void] {
  const { reply, fence } = useContext(FencePlace);
  const [ticks, setTicks] = useState(starting);
  const tapped = useRef(false);
  const shown = useRef(ticks);  // the ticks on screen, for when the saved ones arrive
  useEffect(() => { shown.current = ticks; }, [ticks]);
  const blockPath = `${fence}/${path}`;
  const sessionId = reply?.sessionId;
  const messageKey = reply?.messageKey;

  useEffect(() => {
    if (!sessionId || !messageKey) return;
    const where = { sessionId, messageKey };
    let live = true;
    loadReply(where).then((values) => {
      if (!live) return;
      const next = ticksAfterLoad(readTicks(values[blockPath], count), shown.current, tapped.current);
      setTicks(next.show);
      if (next.save) saveSoon(where, blockPath, next.show);
    }).catch(() => { /* offline: the model's ticks (or the taps) stay */ });
    return () => { live = false; };
  }, [sessionId, messageKey, blockPath, count]);

  function tap(i: number) {
    tapped.current = true;
    const next = toggleTick(ticks, i);
    setTicks(next);
    if (sessionId && messageKey) saveSoon({ sessionId, messageKey }, blockPath, next);
  }
  return [ticks, tap];
}

/**
 * A form's answer, saved with its reply. Returns the answer to show (null: the form is live) and what Send does to
 * keep it. On drawing, the answer saved with the reply wins; without one, an answer a later message carries (the save
 * failed, or another device sent it) is shown instead (answeredState). Sending saves {sent_at, values} at once: never
 * the options, which the reply itself holds.
 */
export function useAnsweredForm(form: FormBlock): [Answered | null, (values: FormValues) => void] {
  const { reply, fence } = useContext(FencePlace);
  const later = useContext(ReplyPlace)?.answers?.[form.id];
  const [saved, setSaved] = useState<Answered | null>(null);
  const blockPath = `${fence}/${form.path}`;
  const sessionId = reply?.sessionId;
  const messageKey = reply?.messageKey;

  useEffect(() => {
    if (!sessionId || !messageKey) return;
    let live = true;
    loadReply({ sessionId, messageKey }).then((values) => {
      if (!live) return;
      const found = readSavedAnswer(values[blockPath], form);
      if (found) setSaved((now) => now ?? found);  // a Send meanwhile is newer
    }).catch(() => { /* offline: a later message's answer, or the live form */ });
    return () => { live = false; };
  }, [sessionId, messageKey, blockPath, form]);

  function markSent(values: FormValues) {
    const at = Date.now();
    setSaved({ at, values });
    if (sessionId && messageKey) saveSoon({ sessionId, messageKey }, blockPath, { sent_at: new Date(at).toISOString(), values }, 0);
  }
  return [answeredState(saved, later), markSent];
}
