// One turn is one message, however many taps it took. A turn's lines share an `inv` (the turn's id): after a reload the
// history's lines of one turn fold into one message, and live, what a resumed run says or does joins the message of its
// turn. The pure functions here do both; Chat.tsx only calls them.
import { drawnText } from "./blocks/drawnText";
import { fenceNumber } from "./blocks/SavedPlace";
import type { Approval } from "./components/ApprovalCard";
import type { Media } from "./media";
import type { ChatEvent } from "./sse";
import { stepFilled, toolStarted, toolWaiting, type Allowed, type HistoryStep, type Tool } from "./steps";
import type { ReplyUsage } from "./usage";

/** One line of `/api/history`. key and sid: the name the server gave a reply and its session (its saved ticks hang off
 * them); inv: the turn the line came from ("" or missing when unknown). */
export type HistoryItem = {
  key?: string; sid?: string; inv?: string; role: "user" | "odie" | "approval"; text: string; tools: string[];
  steps?: HistoryStep[]; ts?: number; images?: string[]; approval?: Approval; media?: Media[]; private?: boolean;
  usage?: ReplyUsage;
};

/** What a message needs for a turn's live events to join it (Chat's Msg has these and more). */
export type TurnMsg = { role: "user" | "odie" | "approval"; inv?: string; text: string; tools: Tool[]; private?: boolean };

// The bus events of a resumed run (after a tap), each naming its turn.
export type StepStartEvent = { type: "step_start"; inv: string; id: string; tool: string; args: Record<string, unknown>; gated: boolean };
export type StepWaitEvent = { type: "step_wait"; inv: string; id: string; tool: string };
export type StepEvent = { type: "step"; inv: string; id: string; tool: string; result: string; allowed?: Allowed };
export type MessageEvent = { type: "message"; inv: string; text: string; private?: boolean };

/** Whether a history line is an approval card that was already answered (approved, rejected or lapsed).
 *    card "approved" -> true;  card "pending" -> false (it still has its buttons);  an Odie line -> false */
function isDecidedCard(item: HistoryItem): boolean {
  if (item.role !== "approval" || !item.approval) return false;
  return item.approval.status !== "pending";
}

/** Whether a line's text holds an ```odie-blocks fence (a checklist, a form) as the chat draws it: its saved ticks
 * and answers hang off the line's key and the fence's number in the drawn text, so nothing may be joined onto it.
 *    "Packing list\n```odie-blocks\n[…]\n```"       -> true
 *    "```odie-checklist\n{…}\n```" (a stray fence)  -> true  (the chat draws it as an odie-blocks fence)
 *    "List ```odie-blocks: […] ```" (one line)     -> true  (lifted onto lines of its own when drawn)
 *    "Added a reminder."                           -> false */
function holdsBlocks(text: string): boolean {
  return fenceNumber(drawnText(text), Infinity) > 0;
}

/** Which line already folded this Odie line continues: the last Odie line, when it is of the same turn, holds no
 * blocks, and only decided cards sit between them. -1 means it starts a message of its own.
 *    [odie A] + odie A                    -> 0
 *    [odie A, card approved] + odie A     -> 0  (the card stays where it was, below the folded line, for now)
 *    [odie A, card pending] + odie A      -> -1 (never across a pending card: its buttons stay in place)
 *    [odie A with a checklist] + odie A   -> -1 (the checklist keeps its key and fence number, so its ticks stay)
 *    [odie A] + odie A with a checklist   -> 0  (the last line's key is kept, and its fences keep their numbers)
 *    [odie A, user A] + odie A            -> -1
 *    [odie B] + odie A, or odie with no turn -> -1 */
function lineToJoin(folded: HistoryItem[], item: HistoryItem): number {
  if (item.role !== "odie" || !item.inv) return -1;
  let at = folded.length - 1;
  while (at >= 0 && isDecidedCard(folded[at])) at -= 1;
  if (at < 0) return -1;
  const before = folded[at];
  if (before.role !== "odie" || before.inv !== item.inv) return -1;
  if (holdsBlocks(before.text)) return -1;
  return at;
}

/** Two lines of one turn as one: texts joined by a blank line (empty ones skipped), steps, tools and media in order,
 * the first line's time, the key (and its session) of the last line that has one, usage from the last that has it;
 * private when either line is. */
function joined(first: HistoryItem, next: HistoryItem): HistoryItem {
  const texts = [first.text, next.text].filter((text) => text);
  const media = [...(first.media ?? []), ...(next.media ?? [])];
  const named = next.key ? next : first;
  return {
    ...first,
    text: texts.join("\n\n"),
    tools: [...first.tools, ...next.tools],
    steps: [...(first.steps ?? []), ...(next.steps ?? [])],
    media: media.length ? media : undefined,
    key: named.key,
    sid: named.sid,
    private: first.private || next.private,
    usage: next.usage ?? first.usage,
  };
}

/** The nearest Odie line on one side of a card (`direction` -1 before, +1 after), looking past other cards only.
 *    [odie, card, card*] before the starred card -> that odie;  [odie, user, card*] -> undefined */
function lineBeside(items: HistoryItem[], from: number, direction: -1 | 1): HistoryItem | undefined {
  let at = from + direction;
  while (at >= 0 && at < items.length && items[at].role === "approval") at += direction;
  const line = items[at];
  if (line?.role !== "odie") return undefined;
  return line;
}

/** Whether a card can go because the step it asked about already tells its answer: it is decided and its call_id is a
 * step of the Odie line right before or right after it (the step's pill says "You allowed · 12:01").
 *    [odie with step c1, card c1 approved]          -> true  (the pill carries it)
 *    [card c1 rejected, odie with step c1]          -> true
 *    [odie with step c1, card c9 approved]          -> false (no step tells it: it stays, as a stamp)
 *    [odie with step c1, card c1 pending]           -> false (its buttons are still needed)
 *    [odie with step c1, user line, card c1]        -> false (not beside it)
 *    a decided card with no call_id (an old row)    -> false */
function toldByStep(items: HistoryItem[], at: number): boolean {
  const card = items[at];
  if (!isDecidedCard(card)) return false;
  const callId = card.approval?.call_id;
  if (!callId) return false;
  const lines = [lineBeside(items, at, -1), lineBeside(items, at, 1)];
  return lines.some((line) => line?.steps?.some((s) => s.id === callId));
}

/** History lines -> the same lines with each turn's consecutive Odie lines folded into one (see lineToJoin and joined),
 * and the decided cards their steps already tell dropped (see toldByStep). Every other line is kept as it was.
 *    [user A, odie A "Sure." c1, card c1 approved, odie A "Removed."] -> [user A, odie A "Sure.\n\nRemoved." c1]
 *    [odie A "Sure." c1, card c1 pending, odie A "…"]                  -> unchanged (the card keeps its place)
 *    [odie A "Asked." c1, card c9 rejected]                            -> unchanged (no step tells card c9) */
export function foldTurns(items: HistoryItem[]): HistoryItem[] {
  const folded: HistoryItem[] = [];
  for (const item of items) {
    const at = lineToJoin(folded, item);
    if (at < 0) folded.push(item);
    else folded[at] = joined(folded[at], item);
  }
  return folded.filter((_, at) => !toldByStep(folded, at));
}

/** Whether a message already ends with these words as a paragraph of their own: the reload after the tap brought
 * them before the live event did.
 *    "Sure.\n\nRemoved." + "Removed." -> true;  "Removed." + "Removed." -> true;  "Removed it." + "it." -> false */
function alreadySaid(text: string, words: string): boolean {
  return text === words || text.endsWith("\n\n" + words);
}

/** A live event of a resumed run joins the message of its turn: the last Odie message with the event's inv.
 *    step_start c2, turn A on screen   -> a running step c2 added (unless that message already has c2)
 *    step_wait c3                      -> c3 waits for your tap
 *    step c1 "removed"                 -> c1 filled with its answer and who allowed it
 *    step_wait or step for an id that message doesn't hold -> null (the caller falls back)
 *    message "Removed."                -> "I'll remove it." becomes "I'll remove it.\n\nRemoved."
 *    message "Removed." on "Sure.\n\nRemoved." or on "Removed." -> the same list (the reload after the tap was first)
 *    message "it." on "Removed it."     -> "Removed it.\n\nit." (only a whole paragraph counts as already there)
 *    message words onto a message holding blocks, or words holding blocks -> null (the caller falls back: a new
 *                                         message, whose ticks wait for the reload to give it its key)
 *    no Odie message of that turn, or the event has no inv -> null (the caller falls back: a new message for words,
 *                                         nothing for steps; the reload after the tap sets things right) */
export function withTurnEvent<M extends TurnMsg>(msgs: M[], e: StepStartEvent | StepWaitEvent | StepEvent | MessageEvent): M[] | null {
  if (!e.inv) return null;
  const at = msgs.findLastIndex((m) => m.role === "odie" && m.inv === e.inv);
  if (at < 0) return null;
  const msg = msgs[at];
  let changed: M;
  if (e.type === "step_start") {
    if (msg.tools.some((t) => t.id === e.id)) return msgs;
    changed = { ...msg, tools: toolStarted(msg.tools, e) };
  } else if (e.type === "step_wait") {
    if (!msg.tools.some((t) => t.id === e.id)) return null;
    changed = { ...msg, tools: toolWaiting(msg.tools, e) };
  } else if (e.type === "step") {
    if (!msg.tools.some((t) => t.id === e.id)) return null;
    changed = { ...msg, tools: stepFilled(msg.tools, e) };
  } else {
    if (alreadySaid(msg.text, e.text)) return msgs;
    if (holdsBlocks(msg.text) || holdsBlocks(e.text)) return null;
    const texts = [msg.text, e.text].filter((text) => text);
    changed = { ...msg, text: texts.join("\n\n"), private: msg.private || !!e.private };
  }
  const next = [...msgs];
  next[at] = changed;
  return next;
}

/** The turn a streaming reply belongs to: the one it already knows, else the stream item's inv when it has one.
 *    known "" + item {inv: "A"}   -> "A"
 *    known "A" + item {inv: "B"}  -> "A" (the first one wins)
 *    known "" + item {inv: ""}, no inv, or not a string -> "" */
export function turnSoFar(known: string, item: ChatEvent): string {
  if (known) return known;
  const inv = (item as { inv?: unknown }).inv;
  if (typeof inv !== "string") return "";
  return inv;
}
