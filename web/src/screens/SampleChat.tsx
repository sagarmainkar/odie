import { useEffect, useState } from "react";
import { loadSample, type ChatTurn, type SavedChat } from "../blocks/eval/chats";
import { Steps } from "../components/Steps";
import { ChatActions } from "../blocks/ChatActions";
import { ReplyText } from "./Chat";

/** #sample: one made-up conversation (evals/sample), turn by turn, drawn by the chat's own Markdown and blocks: what
 *  Odie can show, at a glance. Nobody in it is real. A tap on a row or a button says what it would ask the chat. */
export function SampleChat() {
  const [chat, setChat] = useState<SavedChat | null | undefined>(undefined);
  const [tapped, setTapped] = useState("");
  useEffect(() => {
    loadSample().then(setChat).catch(() => setChat(null));
  }, []);
  return (
    <div className="h-full overflow-y-auto no-scrollbar px-[18px] safe-top flex flex-col gap-5 pb-10">
      <div className="flex items-center gap-3">
        <a href="#settings" aria-label="Back" className="pill w-11 px-0">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 6l-6 6 6 6" /></svg>
        </a>
        <div className="text-[21px] font-bold tracking-[-0.015em]">Sample chat</div>
      </div>
      <div className="px-1 text-[13px] leading-5 text-muted">A made-up conversation, drawn exactly as the chat draws it. Nobody in it is real.</div>
      {chat === undefined && <div className="px-1 text-[13px] text-muted">Loading…</div>}
      {chat === null && <div className="px-1 text-[13px] text-muted">This build has no sample chat.</div>}
      {chat && (
        <ChatActions.Provider value={{ send: (t) => setTapped(`Would ask: “${t}”`), fill: (t) => setTapped(`Would type: “${t}”`), busy: false }}>
          {chat.turns.map((turn) => <ChatTurnView key={turn.n} turn={turn} />)}
        </ChatActions.Provider>
      )}
      {tapped && <div className="fixed left-1/2 -translate-x-1/2 bottom-6 glass glass-solid rounded-full px-4 py-2.5 text-[13px] max-w-[90%] truncate" onClick={() => setTapped("")}>{tapped}</div>}
    </div>
  );
}

/** One turn: the user's bubble, the steps folded into one line as the chat shows them, then the reply. */
function ChatTurnView({ turn }: { turn: ChatTurn }) {
  return (
    <section className="flex flex-col gap-2.5" aria-label={`Turn ${turn.n}`}>
      <div className="ml-auto max-w-[80%] w-fit">
        <div className="bubble-me rounded-[24px] rounded-br-[8px] px-4 py-3 text-[15.5px] leading-[1.5] whitespace-pre-wrap break-words">{turn.user}</div>
      </div>
      <Steps tools={turn.tools.map((t) => ({ name: t.tool, done: true }))} running={false} />
      {turn.media.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {turn.media.map((m, i) => (
            <span key={`m${i}`} className="chip chip-good max-w-full"><span className="truncate">Made a {m.kind ?? "file"}{m.title ? `: ${m.title}` : ""}</span></span>
          ))}
        </div>
      )}
      {turn.reply ? <ReplyText text={turn.reply} /> : <div className="px-1 text-[13px] text-muted">No reply</div>}
    </section>
  );
}
