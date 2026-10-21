import { AnimatePresence, motion } from "framer-motion";
import { useState } from "react";
import { ToBody } from "./ToBody";

/** A drawing from an ```odie-svg fence, already cleaned (svgBlock.ts). It fits the bubble's width; a tap shows it
 * large. An SVG with only a viewBox has no width of its own, so the large view gives it one (92vw, at most 900px) and
 * lets the height follow; left to "auto" it collapsed to a dot. Safe as HTML: DOMPurify's SVG profile has run on it. */
export function SvgBlock({ svg }: { svg: string }) {
  const [open, setOpen] = useState(false);
  return (
    <figure className="my-2" data-visual="svg">
      <button type="button" onClick={() => setOpen(true)} aria-label="Show the drawing larger"
        className="glass glass-solid block w-full rounded-[22px] p-3 text-left [&>svg]:block [&>svg]:w-full [&>svg]:h-auto [&>svg]:max-h-[360px]"
        dangerouslySetInnerHTML={{ __html: svg }} />
      <ToBody>
        <AnimatePresence>
          {open && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setOpen(false)}
              className="fixed inset-0 z-50 bg-black/85 backdrop-blur-md flex items-center justify-center p-4 safe-top safe-bottom" role="dialog" aria-label="Drawing">
              <motion.div initial={{ y: 14, opacity: 0 }} animate={{ y: 0, opacity: 1 }}
                className="bg-white rounded-[28px] p-4 max-w-full max-h-[85vh] overflow-auto [&>svg]:block [&>svg]:w-[min(92vw,900px)] [&>svg]:h-auto [&>svg]:max-h-[78vh]"
                dangerouslySetInnerHTML={{ __html: svg }} />
            </motion.div>
          )}
        </AnimatePresence>
      </ToBody>
    </figure>
  );
}
