// @vitest-environment jsdom
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Face } from "./Face";

describe("the drawn face", () => {
  it("is inline SVG, drawn the same for the same name", () => {
    const a = renderToStaticMarkup(<Face name="Claire" group="female" />);
    expect(a).toBe(renderToStaticMarkup(<Face name="Claire" group="female" />));
    expect(a.startsWith("<svg")).toBe(true);
    expect(a).not.toMatch(/<img|href=|https?:\/\/(?!www\.w3\.org)/);  // nothing fetched from anywhere
  });

  it("differs between two names and between a woman, a man and a character", () => {
    const claire = renderToStaticMarkup(<Face name="Claire" group="female" />);
    expect(renderToStaticMarkup(<Face name="Tom" group="male" />)).not.toBe(claire);
    expect(renderToStaticMarkup(<Face name="Claire" group="Characters" />)).not.toBe(claire);
  });
});
