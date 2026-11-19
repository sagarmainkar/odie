import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Masthead } from "./Masthead";

describe("the masthead", () => {
  it("sets the date line, the name and the counts, the count that needs him in red", () => {
    const html = renderToStaticMarkup(<Masthead dateLine="Thursday, 19 November 2026" counts={{ needs: 4, onIt: 1, done: 6 }} />);
    expect(html).toContain('<span class="masthead-date">Thursday, 19 November 2026</span>');
    expect(html).toContain('<h1 class="masthead-name">Pulse</h1>');
    expect(html).toContain('<span class="masthead-needs">4 need you</span>');
    expect(html.replace(/<[^>]+>/g, "")).toContain("4 need you · 1 on it · 6 done today");
  });
  it("keeps the strip black when nothing needs him", () => {
    const html = renderToStaticMarkup(<Masthead dateLine="x" counts={{ needs: 0, onIt: 2, done: 0 }} />);
    expect(html).not.toContain("masthead-needs");
    expect(html.replace(/<[^>]+>/g, "")).toContain("2 on it");
  });
});
