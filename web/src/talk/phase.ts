// The phases of a talk and what the Talk screen shows in each (components/LocalTalk.tsx).
import type { OrbState } from "../components/Orb";

export type TalkPhase = "connecting" | "listening" | "you" | "thinking" | "speaking" | "error";

/** The face's mood for a phase of the talk: listening while you speak, thinking while the reply comes, speaking while
 *  it's said, resting otherwise.  "you" → "listening"; "thinking" → "thinking"; "connecting" → "idle". */
export function faceFor(phase: TalkPhase): OrbState {
  if (phase === "you" || phase === "listening") return "listening";
  if (phase === "thinking") return "thinking";
  if (phase === "speaking") return "speaking";
  return "idle";
}

/** Whether the Interrupt button shows: while the reply is coming or being said, never while Odie listens.
 *  "speaking" → true; "thinking" → true; "listening" → false. */
export function canInterrupt(phase: TalkPhase): boolean {
  return phase === "speaking" || phase === "thinking";
}
