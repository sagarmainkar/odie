import { useState } from "react";
import { isPhone } from "../install";
import { renderPicture } from "../picture";
import { SMALL_PIECE, canShareHere, shareFile, shareReply, shareWords, visualsIn, whatsappLink, type ShareableFile } from "../share";
import { Icon as Glyph } from "./Tile";

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
 * charts, tables or other drawn pieces, those as pictures too (where the browser has a sheet); on a phone a WhatsApp
 * chip that opens the app with the words ready to send. Nothing at all where neither works (Firefox on a Mac). */
export function ShareWords({ text, title, bubbleId, sheet = canShareHere(), phone = isPhone() }:
                           { text: string; title?: string; bubbleId?: string; sheet?: boolean; phone?: boolean }) {
  const [failed, setFailed] = useState(false);
  const [drawing, setDrawing] = useState(false);
  const words = shareWords(text);
  if (!words || (!sheet && !phone)) return null;
  async function toSheet() {
    const bubble = bubbleId ? document.querySelector(`[data-bubble="${bubbleId}"]`) : null;
    setDrawing(true);
    const outcome = await shareReply({ text: words, title, visuals: visualsIn(bubble, SMALL_PIECE), name: title || "Odie" }, renderPicture);
    setDrawing(false);
    setFailed(outcome === "failed");
    setTimeout(() => setFailed(false), 1500);
  }
  return (
    <>
      {sheet && (
        <button type="button" aria-label={failed ? "Couldn't share" : "Share"} title={failed ? "Couldn't share" : "Share"} disabled={drawing}
          className="hit w-7 h-7 rounded-full flex items-center justify-center text-muted active:text-ink" onClick={() => void toSheet()}>
          {failed ? <span className="text-ember-text"><Cross /></span> : drawing ? <span className="spinner" /> : <ShareIcon />}
        </button>
      )}
      {phone && (
        <a href={whatsappLink(words)} aria-label="Send on WhatsApp" className="hit h-7 pl-1.5 pr-2.5 rounded-full flex items-center gap-1 text-[12px] font-semibold text-muted active:text-ink">
          <Glyph name="chat" size={14} />WhatsApp
        </a>
      )}
    </>
  );
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
