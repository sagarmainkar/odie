// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { cleanSvg } from "./svgBlock";
import { howChatShowsFence } from "./blocks/fenceShown";

const SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50"><rect width="100" height="50" fill="#36c"><animate attributeName="width" from="0" to="100" dur="1s"/></rect><script>alert(1)</script><a href="javascript:alert(2)"><text onclick="x()" x="10" y="30">Hi</text></a></svg>';

describe("cleanSvg", () => {
  it("keeps the drawing and its animation, drops scripts, handlers and script links", () => {
    const out = cleanSvg(SVG)!;
    expect(out).toContain("<rect");
    expect(out).toContain("<animate");
    expect(out).not.toContain("<script");
    expect(out).not.toContain("onclick");
    expect(out).not.toContain("javascript:");
  });
  it("is null for anything that isn't an SVG document", () => {
    expect(cleanSvg("<div>hi</div>")).toBeNull();
    expect(cleanSvg("just words")).toBeNull();
    expect(cleanSvg("")).toBeNull();
  });
});

describe("an odie-svg fence", () => {
  it("is drawn once it is complete, waits while streaming, and reads as code when it isn't SVG", () => {
    const done = howChatShowsFence("odie-svg", SVG);
    expect(done.as).toBe("svg");
    expect(howChatShowsFence("svg", SVG).as).toBe("svg");  // the plain language name works too
    expect(howChatShowsFence("odie-svg", SVG.slice(0, 60)).as).toBe("waiting");
    expect(howChatShowsFence("odie-svg", "<p>not svg</p>").as).toBe("code");
  });
});

describe("cleanSvg and animations that could misbehave", () => {
  it("drops an animation aimed at a link or carrying a script address, keeps the harmless one", () => {
    const svg = '<svg xmlns="http://www.w3.org/2000/svg"><a href="https://ok"><set attributeName="href" to="javascript:alert(1)"/><rect width="4" height="4"><animate attributeName="width" to="10" dur="1s"/><animate attributeName="fill" values="javascript:x;red" dur="1s"/></rect></a></svg>';
    const out = cleanSvg(svg)!;
    expect(out).not.toContain("<set");
    expect(out).not.toContain("javascript");
    expect(out).toContain('attributeName="width"');
  });
});
