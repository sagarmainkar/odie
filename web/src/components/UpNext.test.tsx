// @vitest-environment jsdom
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { UpItem } from "../upnext";
import { UpNext } from "./UpNext";

const item = (over: Partial<UpItem> = {}): UpItem => ({
  id: "cal:1", source: "calendar", sources: [], kind: "birthday", title: "Asha Rao birthday", date: "2026-10-22", time: null,
  end: null, place: null, people: null, amount: null, ask: "Ideas for Asha Rao birthday", ...over,
});

const draw = (items: UpItem[]) => renderToStaticMarkup(<UpNext items={items} loading={false} />);

describe("Up next pictures", () => {
  it("lay a matching photo under the big card's words, behind a veil, and keep the kind's drawing", () => {
    const html = draw([item({ photo: "/api/photos/A2/big" })]);
    expect(html).toContain('src="/api/photos/A2/big"');
    expect(html).toContain("has-photo");
    expect(html).toContain("kind-veil");
    expect(html).toContain("<svg");  // the cake stays
  });

  it("go on the small cards too", () => {
    const html = draw([item({ id: "cal:1" }), item({ id: "cal:2", title: "Diwali", kind: "show", photo: "/api/photos/D2/big" })]);
    expect(html).toContain('src="/api/photos/D2/big"');
    expect(html.match(/has-photo/g)).toHaveLength(1);  // only the card with a picture
  });

  it("leave a card without one as it was", () => {
    const html = draw([item()]);
    expect(html).not.toContain("<img");
    expect(html).not.toContain("has-photo");
  });
});
