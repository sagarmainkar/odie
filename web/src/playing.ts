/** What's playing now, across the app: a memo or podcast player, read-aloud, or a Talk session. A spoken reminder
 * that arrives doesn't play over any of them. */
import { isSpeaking } from "./voice";

let player: string | null = null;
let talking = false;

export function markPlaying(id: string): void { player = id; }
/** Called when a player pauses, ends, or goes away (an unmount pauses it after its listeners are gone). */
export function markStopped(id: string): void { if (player === id) player = null; }
export function setTalking(on: boolean): void { talking = on; }
export function somethingPlaying(): boolean { return player !== null || talking || isSpeaking(); }
