import { AnimatePresence, motion } from "framer-motion";
import { useState } from "react";
import { size } from "../files";
import { mediaUrl, type Media } from "../media";
import { ToBody } from "./ToBody";

/** A picture a tool made (png, jpg, webp, gif, svg): shown under the reply, a tap shows it large. An SVG goes through
 * an img tag, so nothing inside it can run. */
export function PictureCard({ m }: { m: Media }) {
  const [open, setOpen] = useState(false);
  const name = m.filename || m.title;
  return (
    <figure className="my-1" data-media="picture">
      <button type="button" onClick={() => setOpen(true)} aria-label={`Show ${name} larger`} className="glass glass-solid rounded-[22px] p-2 max-w-[460px] text-left">
        <img src={mediaUrl(m)} alt={name} loading="lazy" className="block max-w-full max-h-[360px] object-contain rounded-[16px] bg-well" />
        <figcaption className="px-2 pt-2 pb-1 text-[12.5px] text-muted truncate">{name} · {size(m.size)}</figcaption>
      </button>
      <ToBody>
        <AnimatePresence>
          {open && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setOpen(false)}
              className="fixed inset-0 z-50 bg-black/85 backdrop-blur-md flex flex-col items-center justify-center p-4 safe-top safe-bottom" role="dialog" aria-label="Picture">
              <motion.img initial={{ y: 14, opacity: 0 }} animate={{ y: 0, opacity: 1 }} src={mediaUrl(m)} alt={name} className="max-w-full max-h-[82vh] object-contain rounded-[28px] bg-white" />
              <div className="mt-3 text-center text-[14px] text-white/85">{name}</div>
            </motion.div>
          )}
        </AnimatePresence>
      </ToBody>
    </figure>
  );
}

/** A video a tool made (mp4, webm, mov): the browser's own player, inline on the phone (playsInline). */
export function VideoCard({ m }: { m: Media }) {
  const name = m.filename || m.title;
  return (
    <figure className="my-1 glass glass-solid rounded-[22px] p-2 max-w-[460px]" data-media="video">
      <video src={mediaUrl(m)} controls playsInline preload="metadata" className="block w-full max-h-[360px] rounded-[16px] bg-black" aria-label={name} />
      <figcaption className="px-2 pt-2 pb-1 text-[12.5px] text-muted truncate">{name} · {size(m.size)}</figcaption>
    </figure>
  );
}

/** A sound file a tool made (mp3, m4a, wav): the browser's own player. */
export function AudioCard({ m }: { m: Media }) {
  const name = m.filename || m.title;
  return (
    <figure className="my-1 glass glass-solid rounded-[22px] px-3 py-2.5 max-w-[460px]" data-media="audio">
      <figcaption className="text-[13.5px] font-semibold truncate mb-1.5">{name} <span className="font-normal text-muted">· {size(m.size)}</span></figcaption>
      <audio src={mediaUrl(m)} controls preload="metadata" className="block w-full" aria-label={name} />
    </figure>
  );
}
