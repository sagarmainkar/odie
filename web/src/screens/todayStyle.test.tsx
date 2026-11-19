// @vitest-environment jsdom
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it } from "vitest";
import { Today } from "./Today";
import { PICK_KEY } from "../pick";

// Pulse's head in each style: Glass keeps its greeting; Newspaper sets a masthead with the date line, naming a
// personality on its own Pulse. The first render, before anything has loaded.
afterEach(() => {
  delete document.documentElement.dataset.style;
  localStorage.clear();
});

const text = (html: string) => html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");
const year = String(new Date().getFullYear());

describe("Pulse's head", () => {
  it("in Glass: the greeting, no masthead", () => {
    const html = renderToStaticMarkup(<Today />);
    expect(html).not.toContain("masthead");
    expect(html).toContain("Pulse · ");
  });
  it("in Newspaper: the masthead, dated with the year, and no greeting", () => {
    document.documentElement.dataset.style = "paper";
    const html = renderToStaticMarkup(<Today />);
    expect(html).toContain('<h1 class="masthead-name">Pulse</h1>');
    const date = /<span class="masthead-date">([^<]*)<\/span>/.exec(html)?.[1] ?? "";
    expect(date).toContain(year);
    expect(date).not.toContain(" · ");  // everyday Odie's: the date alone
    expect(html).not.toContain("Pulse · ");
    expect(text(html)).toContain("Nothing needs you");  // nothing loaded yet
  });
  it("on a personality's Pulse, its name joins the date line", () => {
    document.documentElement.dataset.style = "paper";
    localStorage.setItem(PICK_KEY, "abc");
    const html = renderToStaticMarkup(<Today />);
    const date = /<span class="masthead-date">([^<]*)<\/span>/.exec(html)?.[1] ?? "";
    expect(date).toMatch(new RegExp(`^\\S.* · .*${year}$`));
  });
});
