import { AnimatePresence, motion } from "framer-motion";
import { useContext, useState } from "react";
import { PrivateReply } from "../privateReply";
import { heldLabel } from "../signin";
import { uuidOf } from "../ownPhoto";
import { OwnPhotoLarge } from "./OwnPhotoLarge";
import { ToBody } from "./ToBody";

export type ImagesSpec = { title?: string; images: { url: string; caption?: string; source?: string }[] };

/** Odie's own pictures: a thumbnail (or the big copy) the photos route serves, by the uuid the index knows. */
const OWN_PHOTO = /^\/api\/photos\/[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\/(thumb|big)$/;

/** Where a tap opens one of Odie's own photos: its big copy. Anything else opens as it is.
 *  "/api/photos/<uuid>/thumb" → "/api/photos/<uuid>/big";  "https://a/b.jpg" → "https://a/b.jpg" */
export function bigUrl(url: string): string {
  return OWN_PHOTO.test(url) ? url.replace(/\/thumb$/, "/big") : url;
}

/** Parse a ```odie-images block. Only http(s) URLs and Odie's own photo addresses; null when unusable (caller shows the text instead). */
export function parseImages(text: string): ImagesSpec | null {
  let d: any;
  try { d = JSON.parse(text); } catch { return null; }
  const list = Array.isArray(d) ? d : Array.isArray(d?.images) ? d.images : null;
  if (!list) return null;
  const images = list
    .map((x: any) => (typeof x === "string" ? { url: x } : x))
    .filter((x: any) => x && typeof x.url === "string" && (/^https?:\/\//.test(x.url) || OWN_PHOTO.test(x.url)))
    .slice(0, 12)
    .map((x: any) => ({ url: x.url, caption: typeof x.caption === "string" ? x.caption : undefined, source: typeof x.source === "string" ? x.source : undefined }));
  return images.length ? { title: typeof d?.title === "string" ? d.title : undefined, images } : null;
}

/** One image that hides itself if it fails to load (dead links, hotlink blocks). */
export function SafeImage({ src, alt, className, onClick }: { src: string; alt?: string; className?: string; onClick?: () => void }) {
  const [ok, setOk] = useState(true);
  const held = useContext(PrivateReply);
  const [shown, setShown] = useState(!held);
  if (!shown) return <HeldImages urls={[src]} onShow={() => setShown(true)} />;
  if (!ok) return null;
  return <img src={src} alt={alt ?? ""} loading="lazy" referrerPolicy="no-referrer" onError={() => setOk(false)} onClick={onClick} className={className} />;
}

/** Captioned images (search results, news) read as cards; bare photos as a mosaic. */
export function imagesLayout(spec: ImagesSpec): "news" | "mosaic" {
  const captioned = spec.images.filter((i) => i.caption).length;
  return captioned * 2 >= spec.images.length ? "news" : "mosaic";
}

const SOURCE_COLORS = ["#3b66ff", "#ff7430", "#20b679", "#8455ff"];

/** Images a private reply holds until the user taps (signed-in browsing). */
export function HeldImages({ urls, onShow }: { urls: string[]; onShow: () => void }) {
  return (
    <button type="button" onClick={onShow} className="my-2 flex items-center gap-2 rounded-[14px] bg-well px-3.5 py-2.5 text-[13.5px] text-ink-2 text-left active:opacity-80">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden><rect x="3" y="5" width="18" height="14" rx="2" /><circle cx="9" cy="10" r="1.6" /><path d="M21 16l-5-5-8 8" /></svg>
      <span className="flex-1">{heldLabel(urls)}<span className="block text-[12px] text-muted">This chat read a signed-in page, so images wait for your tap.</span></span>
    </button>
  );
}

export function ImageStrip({ spec }: { spec: ImagesSpec }) {
  const held = useContext(PrivateReply);
  const [shown, setShown] = useState(!held);
  if (!shown) return <HeldImages urls={spec.images.map((i) => i.url)} onShow={() => setShown(true)} />;
  return <Strip spec={spec} />;
}

function Strip({ spec }: { spec: ImagesSpec }) {
  const [open, setOpen] = useState<number | null>(null);
  const [failed, setFailed] = useState<Set<number>>(new Set());
  const shown = spec.images.map((im, i) => ({ ...im, i })).filter((im) => !failed.has(im.i));
  if (!shown.length) return null;
  const cur = open !== null ? spec.images[open] : null;
  const fail = (i: number) => setFailed((s) => new Set(s).add(i));
  const layout = imagesLayout(spec);
  const tiles = shown.slice(0, 3);
  return (
    <figure className="imgs my-2">
      {spec.title && <figcaption className="text-[13px] font-semibold text-muted mb-2 px-1">{spec.title}</figcaption>}
      {layout === "news" ? (
        <div className="flex gap-3 overflow-x-auto no-scrollbar -mx-4 px-4 pb-3 snap-x snap-mandatory scroll-px-4 @xl:grid @xl:grid-cols-3 @xl:overflow-visible @xl:mx-0 @xl:px-0">
          {shown.map((im, k) => (
            <button key={im.i} onClick={() => setOpen(im.i)} className="glass glass-solid shrink-0 w-[74%] @xl:w-auto snap-start rounded-[26px] p-2 pb-3.5 text-left">
              <img src={im.url} alt={im.caption ?? ""} loading="lazy" referrerPolicy="no-referrer" onError={() => fail(im.i)}
                className="h-[138px] w-full object-cover rounded-[20px] bg-well" />
              {im.source && (
                <div className="flex items-center gap-1.5 mx-2 mt-3 mb-1.5 text-[12px] font-bold text-muted min-w-0">
                  <i className="w-[18px] h-[18px] shrink-0 rounded-full grid place-items-center not-italic text-[10px] text-white" style={{ background: SOURCE_COLORS[k % 4] }}>{im.source.replace(/^https?:\/\/(www\.)?/, "").charAt(0).toUpperCase()}</i>
                  <span className="truncate">{im.source}</span>
                </div>
              )}
              {im.caption && <div className={`mx-2 text-[15px] leading-[1.35] font-bold line-clamp-2 ${im.source ? "" : "mt-3"}`}>{im.caption}</div>}
            </button>
          ))}
        </div>
      ) : (
        <div className={`grid gap-2 ${tiles.length === 1 ? "grid-cols-1 grid-rows-[240px] @xl:grid-rows-[360px]" : tiles.length === 2 ? "grid-cols-2 grid-rows-[200px] @xl:grid-rows-[300px]" : "grid-cols-[1.4fr_1fr] grid-rows-[130px_110px] @xl:grid-rows-[190px_160px]"}`}>
          {tiles.map((im, k) => (
            <button key={im.i} onClick={() => setOpen(im.i)} className={`relative overflow-hidden rounded-[20px] shadow-[var(--t-shadow-card)] ${tiles.length === 3 && k === 0 ? "row-span-2" : ""}`}>
              <img src={im.url} alt={im.caption ?? ""} loading="lazy" referrerPolicy="no-referrer" onError={() => fail(im.i)} className="w-full h-full object-cover bg-well" />
              {k === 2 && shown.length > 3 && <span className="absolute inset-0 grid place-items-center bg-black/45 text-white text-[20px] font-bold">+{shown.length - 3}</span>}
            </button>
          ))}
        </div>
      )}
      <ToBody>
        <AnimatePresence>
          {cur && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setOpen(null)}
              className="fixed inset-0 z-50 bg-black/85 backdrop-blur-md flex flex-col items-center justify-center p-4 safe-top safe-bottom" role="dialog" aria-label="Image">
              {uuidOf(cur.url) ? <OwnPhotoLarge uuid={uuidOf(cur.url)!} big={bigUrl(cur.url)} caption={cur.caption} /> : (<>
                <motion.img initial={{ y: 14, opacity: 0 }} animate={{ y: 0, opacity: 1 }} src={bigUrl(cur.url)} alt={cur.caption ?? ""} referrerPolicy="no-referrer" className="max-w-full max-h-[78vh] object-contain rounded-[28px]" />
                {(cur.caption || cur.source) && <div className="mt-3 text-center text-[14px] text-white/85">{cur.caption}{cur.source ? <span className="block text-[12px] text-white/55">{cur.source}</span> : null}</div>}
              </>)}
            </motion.div>
          )}
        </AnimatePresence>
      </ToBody>
    </figure>
  );
}
