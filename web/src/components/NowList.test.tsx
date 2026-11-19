import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { NowList } from "./NowList";

const mine = { lines: ["Ship Odie 0.3.1", "Asha's deck by Friday", "Run three times a week"], proposal: null, most: 7 };

describe("the Now list on Pulse", () => {
  it("shows his lines in his order, numbered, with Edit", () => {
    const html = renderToStaticMarkup(<NowList who="Odie" initial={mine} />);
    const shown = [...html.matchAll(/break-words">([^<]+)<\/span>/g)].map((m) => m[1]);
    expect(shown).toEqual(["Ship Odie 0.3.1", "Asha&#x27;s deck by Friday", "Run three times a week"]);
    expect(html).toContain(">Edit</button>");
    expect(html).not.toContain("Draft it for me");
  });
  it("with none yet, offers Odie's first draft or writing it", () => {
    const html = renderToStaticMarkup(<NowList who="Mira" initial={{ lines: [], proposal: null, most: 7 }} />);
    expect(html).toContain("Draft it for me");
    expect(html).toContain("Write it");
    expect(html).toContain("help Mira judge what needs you");
  });
  it("opens the editor with Odie's proposed lines when its card's Edit was tapped", () => {
    const html = renderToStaticMarkup(<NowList who="Odie" initial={mine} editWith={{ lines: ["Ship Odie 0.3.1", "Renew the passport"], proposal: 2 }} />);
    expect(html).toContain('value="Ship Odie 0.3.1"');
    expect(html).toContain('value="Renew the passport"');
    expect(html).toContain("Odie&#x27;s proposal: change what you like, then save.");
    expect(html).toContain(">Save</button>");
    expect(html).toContain("+ Add a line");
    expect(html).toContain('aria-label="Move line 1 up"');
  });
  it("says when the list is full", () => {
    const seven = Array.from({ length: 7 }, (_, i) => `Line ${i + 1}`);
    const html = renderToStaticMarkup(<NowList who="Odie" initial={{ lines: seven, proposal: null, most: 7 }} editWith={{ lines: seven, proposal: 1 }} />);
    expect(html).toContain("7 lines is the most");
  });
});
