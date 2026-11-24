import { motion } from "framer-motion";
import { useEffect, useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { mediaUrl, type Media } from "../media";
import { readerError, readerFormat } from "../reader";
import { CodeBlock } from "./CodeBlock";
import { SafeImage } from "./ImageStrip";
import { ShareFile } from "./ShareButton";
import { Icon } from "./Tile";
import { ToBody } from "./ToBody";

// A report is drawn the way the chat draws a reply (react-markdown, GitHub tables, the .md styles), without the
// chat's own fences (charts, blocks): a report is plain Markdown.
const readerComponents: Components = {
  pre({ children }) {
    const child = Array.isArray(children) ? children[0] : children;
    const props = (child as { props?: { className?: string; children?: ReactNode } })?.props ?? {};
    const lang = (props.className ?? "").replace("language-", "");
    const code = String(props.children ?? "").replace(/\n$/, "");
    return <CodeBlock lang={lang} code={code} />;
  },
  table({ children }) { return <div className="table-wrap"><table>{children}</table></div>; },
  img({ src, alt }) { return typeof src === "string" && /^(https?:\/\/|\/api\/(photos|media)\/)/.test(src) ? <SafeImage src={src} alt={alt} className="my-2 max-w-full rounded-control border border-line" /> : null; },
  a({ href, children }) { return <a href={href} target="_blank" rel="noreferrer">{children}</a>; },
};

type Loaded = { state: "loading" } | { state: "shown"; text: string } | { state: "failed"; why: string };

/** The file's text, fetched from the same address the card downloads from. */
function useFileText(m: Media): Loaded {
  const [loaded, setLoaded] = useState<Loaded>({ state: "loading" });
  useEffect(() => {
    let stillOpen = true;
    async function load() {
      let got: Loaded;
      try {
        const r = await fetch(mediaUrl(m));
        if (r.ok) got = { state: "shown", text: await r.text() };
        else got = { state: "failed", why: readerError(r.status) };
      } catch {
        got = { state: "failed", why: "Couldn't reach Odie. Check the connection and try again." };
      }
      if (stillOpen) setLoaded(got);
    }
    void load();
    return () => { stillOpen = false; };
  }, [m]);
  return loaded;
}

/** A Markdown or text file opened inside Odie, full screen: the report formatted in a reading column, with Close,
 * Download and Share on top. Escape closes it on a desk. */
export function ReportReader({ m, onClose }: { m: Media; onClose: () => void }) {
  const name = m.filename || m.title;
  const format = readerFormat(name);
  const loaded = useFileText(m);
  useEffect(() => {
    function onKey(e: KeyboardEvent) { if (e.key === "Escape") onClose(); }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <ToBody>
      <motion.div initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.2 }}
        role="dialog" aria-modal="true" aria-label={name} data-reader
        className="fixed inset-0 z-50 bg-ground flex flex-col safe-top safe-bottom">
        <div className="flex items-center gap-2 px-3 sm:px-5 py-2 border-b border-line">
          <button type="button" onClick={onClose} aria-label="Close" className="shrink-0 w-9 h-9 rounded-full bg-well text-ink grid place-items-center">
            <Icon name="x" size={17} />
          </button>
          <b className="flex-1 min-w-0 truncate text-ui font-semibold">{name}</b>
          <a href={mediaUrl(m)} download={name} aria-label={`Download ${name}`} title="Download"
            className="shrink-0 w-9 h-9 rounded-full bg-well text-ink-2 grid place-items-center rotate-180 active:bg-line">
            <Icon name="up" size={17} />
          </a>
          <ShareFile file={m} />
        </div>
        <div className="flex-1 overflow-y-auto overscroll-contain [touch-action:pan-x_pan-y_pinch-zoom]">
          <article className="reader md mx-auto w-full max-w-[720px] px-5 sm:px-8 pt-5 pb-12">
            {loaded.state === "loading" && <p className="text-muted flex items-center gap-2"><span className="spinner" />Opening…</p>}
            {loaded.state === "failed" && <p className="text-muted">{loaded.why}</p>}
            {loaded.state === "shown" && format === "markdown" && <ReactMarkdown remarkPlugins={[remarkGfm]} components={readerComponents}>{loaded.text}</ReactMarkdown>}
            {loaded.state === "shown" && format !== "markdown" && <div className="whitespace-pre-wrap">{loaded.text}</div>}
          </article>
        </div>
      </motion.div>
    </ToBody>
  );
}
