import { useState } from "react";
import { renderPicture } from "../picture";
import { SMALL_PIECE, canShareHere, shareFile, shareReply, shareWords, visualsIn, type ShareableFile } from "../share";

function ShareIcon({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 3v12" /><path d="M8 7l4-4 4 4" /><path d="M4 13v6a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-6" />
    </svg>
  );
}

function Cross({ size = 16 }: { size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>;
}

/** Under a reply: the share sheet with its words and, when the bubble (`bubbleId`, the reply's data-bubble) holds
 * charts, tables or other drawn pieces, those as pictures too. Nothing where the browser has no sheet (Firefox on a
 * Mac). When the pictures could not go, a line under the row says so and why, for a while. */
export function ShareWords({ text, title, bubbleId, sheet = canShareHere() }: { text: string; title?: string; bubbleId?: string; sheet?: boolean }) {
  const [note, setNote] = useState("");
  const [failed, setFailed] = useState(false);
  const [drawing, setDrawing] = useState(false);
  const words = shareWords(text);
  if (!words || !sheet) return null;
  async function toSheet() {
    const bubble = bubbleId ? document.querySelector(`[data-bubble="${bubbleId}"]`) : null;
    const visuals = visualsIn(bubble, SMALL_PIECE);
    setDrawing(true);
    const went = await shareReply({ text: words, title, visuals, name: title || "Odie" }, renderPicture);
    setDrawing(false);
    setFailed(went.outcome === "failed");
    setNote(wordsAloneNote(visuals.length, went));
    setTimeout(() => { setFailed(false); setNote(""); }, 6000);
  }
  return (
    <>
      <button type="button" aria-label={failed ? "Couldn't share" : "Share"} title={failed ? "Couldn't share" : "Share"} disabled={drawing}
        className="hit w-7 h-7 rounded-full flex items-center justify-center text-muted active:text-ink" onClick={() => void toSheet()}>
        {failed ? <span className="text-ember-text"><Cross /></span> : drawing ? <span className="spinner" /> : <ShareIcon />}
      </button>
      {note && <span className="text-[12px] text-muted">{note}</span>}
    </>
  );
}

/** The line under the row after a share: nothing when the pictures went (or there were none to send); otherwise
 * that the words went alone, and why. (2 pieces, {shared, 0, why "the browser gave no picture"}) ->
 * "Words only: the browser gave no picture"; (0 pieces, {shared, 0}) -> ""; (2, {cancelled, 0, why}) -> "" */
export function wordsAloneNote(pieces: number, went: { outcome: string; pictures: number; why?: string }): string {
  if (!pieces || went.pictures > 0 || went.outcome !== "shared") return "";
  return `Words only: ${went.why || "the pictures couldn't be drawn"}`;
}

/** On a made file's card (a deck's PDF, a podcast, a picture): the share sheet with the file attached, so it can go to
 * WhatsApp, Messages, Mail or AirDrop. Nothing where the browser has no sheet; the download stays beside it. */
export function ShareFile({ file, sheet = canShareHere(), dark = false }: { file: ShareableFile; sheet?: boolean; dark?: boolean }) {
  const [note, setNote] = useState<"" | "failed" | "unsupported">("");
  if (!sheet) return null;
  async function toSheet() {
    const outcome = await shareFile(file);
    setNote(outcome === "failed" || outcome === "unsupported" ? outcome : "");
    setTimeout(() => setNote(""), 2000);
  }
  const label = note === "failed" ? "Couldn't share the file" : note === "unsupported" ? "This browser can't share files; download it instead" : "Share";
  return (
    <button type="button" aria-label={label} title={label}
      onClick={(e) => { e.preventDefault(); e.stopPropagation(); void toSheet(); }}
      className={`shrink-0 w-9 h-9 rounded-full grid place-items-center ${dark ? "bg-white/15 text-white" : "bg-well text-ink-2 active:bg-line"}`}>
      {note ? <span className="text-ember-text"><Cross /></span> : <ShareIcon />}
    </button>
  );
}
