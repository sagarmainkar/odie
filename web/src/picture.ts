/** A reply's visual piece (a chart, a table, a heat map, a diagram) as a picture, for the share sheet: the piece as
 * it is drawn, on a solid ground with a small Odie line under it, so it reads as a card in WhatsApp or Messages. */

const FRAME_PAD = 16;
const BASE_WIDTH = 560;
const MAX_WIDTH = 1200;  // a picture never grows wider than this, however wide the table

/** The card a piece is drawn on for its picture: the piece's own width plus padding, the page's ground colour and
 * body font, with a small line under it. It sits in a frame off screen while it renders; the card, not the frame,
 * is what gets drawn, since a drawing copies the node's own position too. */
function cardFor(piece: HTMLElement, name: string): { frame: HTMLElement; card: HTMLElement } {
  const styles = getComputedStyle(document.documentElement);
  const frame = document.createElement("div");
  Object.assign(frame.style, { position: "fixed", left: "-10000px", top: "0", pointerEvents: "none" } as Partial<CSSStyleDeclaration>);
  const card = document.createElement("div");
  card.className = "md";
  Object.assign(card.style, {
    padding: `${FRAME_PAD}px`, boxSizing: "border-box",
    background: styles.getPropertyValue("--t-ground").trim() || "#fff", color: styles.getPropertyValue("--t-ink").trim() || "#000",
    fontFamily: styles.getPropertyValue("--font-body").trim() || "sans-serif",
  } as Partial<CSSStyleDeclaration>);
  const copy = piece.cloneNode(true) as HTMLElement;
  for (const hidden of copy.querySelectorAll("[data-share-hide]")) hidden.remove();
  // the picture is at least a tablet's width, so a heat map's or table's labels get room a phone could not give;
  // a part that scrolls sideways on the phone (a wide table) is let out whole instead
  const originals = Array.from(piece.querySelectorAll<HTMLElement>("*"));
  const copies = Array.from(copy.querySelectorAll<HTMLElement>("*"));
  const own = Math.ceil(piece.getBoundingClientRect().width);
  let widest = Math.max(own, BASE_WIDTH);
  originals.forEach((el, i) => {
    const overflow = getComputedStyle(el).overflowX;
    if ((overflow !== "auto" && overflow !== "scroll") || el.scrollWidth <= el.clientWidth + 1) return;
    widest = Math.max(widest, Math.min(el.scrollWidth + (own - el.clientWidth), MAX_WIDTH));
    copies[i].style.overflow = "visible";
  });
  card.style.width = `${widest + FRAME_PAD * 2}px`;
  card.append(copy);
  const line = document.createElement("div");
  line.textContent = `${name} · ${new Date().toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}`;
  Object.assign(line.style, { marginTop: "10px", fontSize: "11.5px", fontWeight: "600", letterSpacing: "0.04em", opacity: "0.55" } as Partial<CSSStyleDeclaration>);
  card.append(line);
  frame.append(card);
  return { frame, card };
}

/** What a render gives: the PNG file, or why there is none (the words then go alone and the button says so). */
export type Drawn = { file: File | null; why?: string };

/** The piece as a PNG file at twice the screen's scale, or why it could not be drawn. `name` is the assistant's
 * name, on the line under the picture. Drawn twice: Safari fills in fonts and pictures only on a second pass. */
export async function renderPicture(piece: HTMLElement, name: string, fileName: string): Promise<Drawn> {
  const { toBlob } = await import("html-to-image");
  const { frame, card } = cardFor(piece, name);
  document.body.append(frame);
  try {
    await toBlob(card, { pixelRatio: 2, cacheBust: false });
    const blob = await toBlob(card, { pixelRatio: 2, cacheBust: false });
    if (!blob) return { file: null, why: "the browser gave no picture" };
    return { file: new File([blob], fileName, { type: "image/png" }) };
  } catch (error) {
    const said = (error as { message?: string } | null)?.message || String(error);
    return { file: null, why: said.slice(0, 120) };
  } finally {
    frame.remove();
  }
}
