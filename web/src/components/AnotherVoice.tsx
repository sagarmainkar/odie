import { useState } from "react";
import { anotherLine, canTry, NAME_LIMIT, triedState, tryAnotherVoice, type AnotherState, type PhononAnswer } from "../voiceSettings";

type ViewProps = { name: string; state: AnotherState; onName: (name: string) => void; onTry: () => void };

/** The "Another voice" box under Phonon's voices: a name, "Try it", and a line that says how the try went. */
export function AnotherVoiceView({ name, state, onName, onTry }: ViewProps) {
  const line = anotherLine(state);
  const refused = state.kind === "refused";
  return (
    <div className="flex flex-col gap-1.5">
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (canTry(name, state)) onTry(); }}>
        <input value={name} onChange={(e) => onName(e.target.value)} placeholder="Another voice name" aria-label="Another voice name"
          maxLength={NAME_LIMIT + 20} className="flex-1 min-w-0 h-11 rounded-[12px] border border-line bg-surface px-3 text-[15px]" />
        <button type="submit" disabled={!canTry(name, state)} className="h-11 px-4 rounded-[12px] bg-well text-[14px] font-semibold disabled:opacity-40">Try it</button>
      </form>
      {line && <div role="status" className={`text-[12.5px] leading-[18px] px-1 ${refused ? "text-warn" : "text-muted"}`}>{line}</div>}
    </div>
  );
}

/** "Another voice", wired: the try goes to the server, a kept voice updates the picker and plays its preview. */
export function AnotherVoice({ onKept }: { onKept: (answer: PhononAnswer) => void }) {
  const [name, setName] = useState("");
  const [state, setState] = useState<AnotherState>({ kind: "idle" });
  async function tryIt() {
    setState({ kind: "trying" });
    const got = await tryAnotherVoice(name.trim());
    if (!got.ok) { setState({ kind: "refused", message: got.message }); return; }
    setState(triedState(got.answer, name.trim()));
    setName("");
    onKept(got.answer);
  }
  return <AnotherVoiceView name={name} state={state} onName={(n) => { setName(n); if (state.kind !== "trying") setState({ kind: "idle" }); }} onTry={() => void tryIt()} />;
}
