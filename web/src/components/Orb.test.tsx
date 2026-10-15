import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Orb } from "./Orb";

describe("Odie's face", () => {
  it("is a face with two eyes and a mouth, named by its state", () => {
    const html = renderToStaticMarkup(<Orb state="idle" size={40} />);
    expect(html).toContain('aria-label="idle"');
    expect(html).toContain("orb breathe");
    expect((html.match(/class="face-eye"/g) ?? []).length).toBe(2);
    expect(html).toContain('class="face-mouth"');
  });
  it("carries the state as a class the CSS animates: thinking rolls its eyes under the ring, approval raises a brow", () => {
    expect(renderToStaticMarkup(<Orb state="thinking" />)).toContain("orb is-thinking");
    expect(renderToStaticMarkup(<Orb state="thinking" />)).toContain('class="face-ring"');
    expect(renderToStaticMarkup(<Orb state="approval" />)).toContain("orb is-approval");
    expect(renderToStaticMarkup(<Orb state="speaking" halo />)).toContain("orb is-speaking orb-halo");
  });
});
