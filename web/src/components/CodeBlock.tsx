import { useEffect, useMemo, useState } from "react";
import { highlighterIfLoaded, loadHighlighter } from "../lazy";
import { CopyButton } from "./CopyButton";

type Highlighter = typeof import("../highlight");

/**
 * A fenced code block in a reply: its language and a Copy button on top, the code coloured below. The code shows
 * plain at once and takes its colours when the highlighter has arrived (the first time only; it is kept after).
 * Copy always copies the code exactly as the model wrote it, never the coloured HTML.
 */
export function CodeBlock({ lang, code }: { lang: string; code: string }) {
  const [highlighter, setHighlighter] = useState<Highlighter | null>(highlighterIfLoaded);
  useEffect(() => {
    if (highlighter) return;
    let stillShown = true;
    loadHighlighter()
      .then((module) => { if (stillShown) setHighlighter(module); })
      .catch(() => { /* offline or the file is gone: the code stays plain */ });
    return () => { stillShown = false; };
  }, [highlighter]);
  const coloured = useMemo(() => highlighter?.colourCode(code, lang) ?? null, [highlighter, code, lang]);
  const codeClass = lang ? `language-${lang}` : undefined;
  return (
    <div className="codeblock">
      <div className="codeblock-bar"><span>{lang || "code"}</span><CopyButton text={code} label="Copy code" /></div>
      <pre>
        {coloured === null
          ? <code className={codeClass}>{code}</code>
          // Safe as HTML: colourCode's highlighter escapes the code and adds only its own <span class="hljs-…"> tags.
          : <code className={`hljs ${codeClass}`} dangerouslySetInnerHTML={{ __html: coloured }} />}
      </pre>
    </div>
  );
}
