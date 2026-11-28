// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Media } from "../media";
import { FileCard } from "./FileCard";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const report: Media = { id: "a1b2c3d4e5f60718", kind: "file", title: "Local models", mime: "text/markdown", size: 2048, created: 0, filename: "local-models.md" };
const REPORT_TEXT = "# Local models\n\nA short answer.\n\n| Model | Note |\n| --- | --- |\n| Small | fast |\n\n- one\n- two\n";

let root: Root | null = null;
afterEach(() => {
  act(() => root?.unmount());
  root = null;
  document.body.innerHTML = "";
  vi.unstubAllGlobals();
});

async function openCard(m: Media, answer: Response) {
  const fetched = vi.fn(async () => answer);
  vi.stubGlobal("fetch", fetched);
  const host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  act(() => root!.render(<FileCard m={m} />));
  const read = host.querySelector<HTMLButtonElement>('button[aria-label^="Read"]')!;
  await act(async () => { read.click(); });
  await act(async () => { await Promise.resolve(); });
  return fetched;
}

describe("a report's file card", () => {
  it("offers Read instead of a download for Markdown, and keeps the download for other files", () => {
    const md = renderToStaticMarkup(<FileCard m={report} />);
    expect(md).toContain('aria-label="Read local-models.md, Text, 2 KB"');
    expect(md).toContain(">Read<");
    expect(md).not.toContain("download=");
    const pdf = renderToStaticMarkup(<FileCard m={{ ...report, mime: "application/pdf", filename: "local-models.pdf" }} />);
    expect(pdf).toContain("download=");
    expect(pdf).not.toContain(">Read<");
  });

  it("opens the report formatted, fetched from the card's own address, with Download in the reader", async () => {
    const fetched = await openCard(report, new Response(REPORT_TEXT, { headers: { "Content-Type": "text/markdown" } }));
    expect(fetched).toHaveBeenCalledWith("/api/media/a1b2c3d4e5f60718");
    const reader = document.querySelector("[data-reader]")!;
    expect(reader.querySelector("h1")?.textContent).toBe("Local models");
    expect(reader.querySelector(".table-wrap table")).not.toBeNull();
    expect(reader.querySelectorAll("li").length).toBe(2);
    expect(reader.querySelector('a[download="local-models.md"]')).not.toBeNull();
    act(() => reader.querySelector<HTMLButtonElement>('button[aria-label="Close"]')!.click());
    expect(document.querySelector("[data-reader]")).toBeNull();
  });

  it("shows a text file as written", async () => {
    await openCard({ ...report, mime: "text/plain", filename: "list.txt" }, new Response("# not a heading\nline two"));
    const reader = document.querySelector("[data-reader]")!;
    expect(reader.querySelector("h1")).toBeNull();
    expect(reader.textContent).toContain("# not a heading\nline two");
  });

  it("says so when the file is gone", async () => {
    await openCard(report, new Response("", { status: 404 }));
    expect(document.querySelector("[data-reader]")!.textContent).toContain("This file isn't on Odie any more.");
  });
});
