import { useState } from "react";
import type { ReactNode } from "react";
import { copyText } from "../copy";

function Icon({ d, children }: { d?: string; children?: ReactNode }) {
  return <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">{d ? <path d={d} /> : children}</svg>;
}

/** A small round button that copies `text`: a tick when it worked, a cross when the browser refused. */
export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [done, setDone] = useState<"" | "copied" | "failed">("");
  async function copy() {
    setDone((await copyText(text)) ? "copied" : "failed");
    setTimeout(() => setDone(""), 1500);
  }
  return (
    <button type="button" aria-label={done === "failed" ? "Couldn't copy" : label} title={done === "failed" ? "Couldn't copy: select the text instead" : label}
      className="hit w-7 h-7 rounded-full flex items-center justify-center text-muted active:text-ink" onClick={() => void copy()}>
      {done === "copied" ? <span className="text-moss-text"><Icon d="M5 13l4 4L19 7" /></span>
        : done === "failed" ? <span className="text-ember-text"><Icon d="M6 6l12 12M18 6L6 18" /></span>
        : <Icon><rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15V5a2 2 0 0 1 2-2h10" /></Icon>}
    </button>
  );
}
