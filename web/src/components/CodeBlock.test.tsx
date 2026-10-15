// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { copyText } from "../copy";
import { ReplyText } from "../screens/Chat";
import { loadHighlighter } from "../lazy";
import { CodeBlock } from "./CodeBlock";

vi.mock("../copy", () => ({ copyText: vi.fn(async () => true) }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

beforeAll(async () => {
  await loadHighlighter();  // once fetched, every code box colours on its first draw
});

describe("a code box", () => {
  it("colours a language it knows, by its short name too", () => {
    const html = renderToStaticMarkup(<CodeBlock lang="py" code={"def emi(p):\n    return p  # monthly"} />);
    expect(html).toContain('<span class="hljs-keyword">def</span>');
    expect(html).toContain('<span class="hljs-comment"># monthly</span>');
  });

  it("colours JSON keys and values", () => {
    const html = renderToStaticMarkup(<CodeBlock lang="json" code={'{"city": "Ooty", "days": 3}'} />);
    expect(html).toContain('<span class="hljs-attr">&quot;city&quot;</span>');
    expect(html).toContain('<span class="hljs-number">3</span>');
  });

  it("leaves a language it doesn't know as plain text", () => {
    const html = renderToStaticMarkup(<CodeBlock lang="cobol" code="MOVE A TO B." />);
    expect(html).not.toContain("hljs");
    expect(html).toContain("<code class=\"language-cobol\">MOVE A TO B.</code>");
  });

  it("never lets the model's text through as HTML", () => {
    const html = renderToStaticMarkup(<CodeBlock lang="javascript" code={'el.innerHTML = "<img src=x onerror=alert(1)>";'} />);
    expect(html).not.toContain("<img");
    expect(html).toContain("&lt;img src=x onerror=alert(1)&gt;");
  });

  it("copies the code exactly as written, not the coloured HTML", async () => {
    const code = "def f():\n    return '<b>'";
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    await act(async () => root.render(<CodeBlock lang="python" code={code} />));
    const button = host.querySelector<HTMLButtonElement>('button[aria-label="Copy code"]')!;
    await act(async () => button.click());
    expect(copyText).toHaveBeenCalledWith(code);
    act(() => root.unmount());
  });
});

describe("Odie's own fences in a reply", () => {
  it("are still drawn as blocks, never as a code box, beside a coloured code fence", () => {
    const text = 'Here:\n\n```odie-blocks\n[{"type": "callout", "text": "Hi"}]\n```\n\n```python\nprint(1)\n```';
    const html = renderToStaticMarkup(<ReplyText text={text} />);
    expect(html).not.toContain("language-odie-blocks");
    expect(html).toContain("Hi");
    expect(html.match(/class="codeblock"/g)).toHaveLength(1);
    expect(html).toContain('<span class="hljs-built_in">print</span>');
  });
});
