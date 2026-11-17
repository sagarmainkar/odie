import { withPickOf } from "./pick";

// Settings has no list of personalities. Its name, picture and personality boxes show and edit whoever is picked in
// the chat's switcher: it is a context switch. These are the small decisions that make it so.

/** Where the name is read and saved: always saying who, even everyday Odie ("" -> "?personality="). */
export function personaUrl(pick: string): string { return withPickOf("/api/persona", pick, true); }

export function avatarUrl(pick: string): string { return withPickOf("/api/persona/avatar", pick, true); }

export function soulUrl(pick: string): string { return withPickOf("/api/soul", pick, true); }

/** Delete is offered for a personality, never for everyday Odie:  "abc" -> true;  "" -> false. */
export function showsDelete(pick: string): boolean { return pick !== ""; }

/** Whether Settings says who is being edited: only once there is someone else to edit, so an install with no
 *  personalities looks as it always has:  ("", 0) -> false;  ("", 2) -> true;  ("abc", 1) -> true. */
export function showsWhoLine(pick: string, howMany: number): boolean { return pick !== "" || howMany > 0; }

export function whoLine(name: string): string { return `Editing ${name}`; }

/** The question before a personality is deleted: what goes with it, and what Odie can't reach. */
export function deleteWords(name: string, threads: number): string {
  let what = `Delete ${name}?`;
  if (threads === 1) what = `Delete ${name} and its 1 thread?`;
  if (threads > 1) what = `Delete ${name} and its ${threads} threads?`;
  return `${what} Its threads, memory, instructions and picture are erased for good, and so are the debug copies of `
    + "recent model requests. Not erased: log lines, and anything already sent to a tracing service.";
}
