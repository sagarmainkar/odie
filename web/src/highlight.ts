// Colours for code in replies. This file is fetched only the first time a code box is drawn (CodeBlock.tsx imports it
// with import()), so the app's first load doesn't carry the highlighter. highlight.js core with the languages replies
// use most; each language also answers to its short names (py, js, ts, sh, yml, html…).
import hljs from "highlight.js/lib/core";
import bash from "highlight.js/lib/languages/bash";
import css from "highlight.js/lib/languages/css";
import javascript from "highlight.js/lib/languages/javascript";
import json from "highlight.js/lib/languages/json";
import python from "highlight.js/lib/languages/python";
import sql from "highlight.js/lib/languages/sql";
import typescript from "highlight.js/lib/languages/typescript";
import xml from "highlight.js/lib/languages/xml";
import yaml from "highlight.js/lib/languages/yaml";

hljs.registerLanguage("bash", bash);
hljs.registerLanguage("css", css);
hljs.registerLanguage("javascript", javascript);
hljs.registerLanguage("json", json);
hljs.registerLanguage("python", python);
hljs.registerLanguage("sql", sql);
hljs.registerLanguage("typescript", typescript);
hljs.registerLanguage("xml", xml);
hljs.registerLanguage("yaml", yaml);

/**
 * The code as HTML with coloured spans, or null when the language isn't one we colour (then it stays plain text).
 * highlight.js escapes the code itself (< becomes &lt;), so the model's text never reaches the page as HTML.
 *   ("python", "def f(): pass")  → '<span class="hljs-keyword">def</span> <span class="hljs-title function_">f</span>…'
 *   ("py", "x = 1")              → coloured too (a short name)
 *   ("cobol", "MOVE A TO B")     → null
 *   ("", "anything")             → null
 */
export function colourCode(code: string, lang: string): string | null {
  if (!lang || !hljs.getLanguage(lang)) return null;
  return hljs.highlight(code, { language: lang, ignoreIllegals: true }).value;
}
