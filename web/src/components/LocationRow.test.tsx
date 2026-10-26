// @vitest-environment jsdom
import { renderToStaticMarkup } from "react-dom/server";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import { NOTE_TEXT, type LocationInfo } from "../location";
import { LocationRowView, type RowParts } from "./LocationRow";

// A stand-in for Settings' Row: it marks where its sub and meta land, so the test can see what sits in the text column.
function StubRow({ title, sub, meta, right }: RowParts): ReactNode {
  return <div data-row><b>{title}</b><div data-slot="sub">{sub}</div><div data-slot="meta">{meta}</div><div data-slot="right">{right}</div></div>;
}

const info: LocationInfo = { on: true, place: "City of Northvale, Westshire", seen: "2026-10-25T14:12:00+05:30", home: "Northvale", home_set_by_user: false };
const now = new Date("2026-10-25T14:16:00+05:30");

describe("the Location row", () => {
  it("draws the note under the row, across its full width, not in the text column", () => {
    const html = renderToStaticMarkup(<LocationRowView info={info} now={now} busy={false} Row={StubRow} onTurnOn={() => {}} onOff={() => {}} onForget={() => {}} />);
    const row = html.indexOf("<div data-row>");
    const rowEnd = html.indexOf("</div></div>", row) + "</div></div>".length;  // the stub row closes here
    const note = html.indexOf(NOTE_TEXT);
    expect(note).toBeGreaterThan(rowEnd);                                  // the note comes after the whole row
    expect(html.slice(row, rowEnd)).not.toContain(NOTE_TEXT);             // and nowhere inside its sub, meta or right slots
    expect(html).toContain('data-slot="sub">City of Northvale, Westshire<');
    expect(html).toContain('data-slot="meta">seen 14:12 · home Northvale<');
    expect(html).toMatch(/class="[^"]*location-note[^"]*"[^>]*>Your model gets the place name/);  // its own full-width line
  });

  it("offers Off and Forget when on with a place, Turn on when off", () => {
    const on = renderToStaticMarkup(<LocationRowView info={info} now={now} busy={false} Row={StubRow} onTurnOn={() => {}} onOff={() => {}} onForget={() => {}} />);
    expect(on).toContain(">Off<");
    expect(on).toContain(">Forget<");
    const off = renderToStaticMarkup(<LocationRowView info={{ ...info, on: false, place: "", home: "" }} now={now} busy={false} Row={StubRow} onTurnOn={() => {}} onOff={() => {}} onForget={() => {}} />);
    expect(off).toContain(">Turn on<");
    expect(off).not.toContain(">Forget<");
  });
});
