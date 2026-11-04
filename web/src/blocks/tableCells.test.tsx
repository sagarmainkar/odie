// Change columns, mini bars and big amounts in tables (tableCells.ts), and how Table.tsx draws them.
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it } from "vitest";
import { rememberLocale } from "../locale";
import { Blocks } from "./Blocks";
import { readBlocks } from "./parse";
import { bigNumber, changeOf, isChangeColumn, miniBar } from "./tableCells";
import { cellNumber } from "./tableSort";

afterEach(() => rememberLocale("en-IN"));

const draw = (json: unknown) => renderToStaticMarkup(<Blocks blocks={readBlocks(JSON.stringify(json))!.blocks} />);

describe("change columns", () => {
  it("are number columns with a sign written somewhere, all percentages or all signed", () => {
    expect(isChangeColumn([["A", "+5%"], ["B", "-3%"]], 1)).toBe(true);
    expect(isChangeColumn([["A", "4.1%"], ["B", "−2.0%"]], 1)).toBe(true);
    expect(isChangeColumn([["A", "+120"], ["B", "-40"], ["C", "0"]], 1)).toBe(true);
  });
  it("leave prices, plain numbers, words and empty columns alone", () => {
    expect(isChangeColumn([["A", "₹300"], ["B", "₹50"]], 1)).toBe(false);
    expect(isChangeColumn([["A", "4.1"], ["B", "2.3"]], 1)).toBe(false);
    expect(isChangeColumn([["A", "+5%"], ["B", "n/a"]], 1)).toBe(false);
    expect(isChangeColumn([["A", ""], ["B", ""]], 1)).toBe(false);
  });
  it("leave a column of mixed metrics alone, so P/E 13.3 beside +4.7% stays plain", () => {
    const metricsByRow = [["1-year price change", "-26.77%"], ["P/E", "13.3"], ["P/B", "1.83"], ["PAT growth YoY", "+4.7%"]];
    expect(isChangeColumn(metricsByRow, 1)).toBe(false);
  });
  it("read each cell as a rise, a fall or neither, a typeset minus included", () => {
    expect(changeOf("+1.76%")).toBe("up");
    expect(changeOf("−18.67%")).toBe("down");
    expect(changeOf("0.00%")).toBeNull();
    expect(changeOf("")).toBeNull();
    expect(cellNumber("−4.1%")).toBe(-4.1);
    expect(cellNumber("-$279.84")).toBe(-279.84);
  });
});

describe("mini bars", () => {
  it("grow from the middle, right for a rise and left for a fall", () => {
    expect(miniBar(5, 10)).toEqual({ left: 50, width: 25 });
    expect(miniBar(-10, 10)).toEqual({ left: 0, width: 50 });
    expect(miniBar(0, 0)).toEqual({ left: 50, width: 0 });
  });
});

describe("big amounts in cells", () => {
  it("shorten a written-out amount from 100,000 up and keep every digit for the title", () => {
    rememberLocale("en-US");
    expect(bigNumber("1,250,000")).toEqual({ short: "1.25M", full: "1,250,000" });
    expect(bigNumber("-$4,213,500,000")).toEqual({ short: "-$4.21B", full: "-$4,213,500,000" });
    expect(bigNumber("₹18,40,000")).toEqual({ short: "₹18.4L", full: "₹18,40,000" });
    expect(bigNumber("+1,250,000")).toEqual({ short: "+1.25M", full: "+1,250,000" });
  });
  it("leave codes, small numbers and numbers with words alone", () => {
    expect(bigNumber("560001")).toBeNull();  // a PIN code or an id: no grouping, no currency
    expect(bigNumber("99,999")).toBeNull();
    expect(bigNumber("4,800 mAh")).toBeNull();
    expect(bigNumber("Pixel 10a")).toBeNull();
  });
});

describe("drawing a table", () => {
  const sectors = { type: "table", columns: ["Sector", "Index", "Today", "P/E"], highlight: { row: 0 },
    rows: [["IT", "₹38,412", "+1.84%", "29.4"], ["Bank", "₹51,220", "+0.42%", "14.2"], ["Realty", "₹946", "−1.72%", "41.5"]] };

  it("colours rises and falls in a change column only, with a mini bar each", () => {
    const html = draw([sectors]);
    expect(html.match(/text-good/g)).toHaveLength(2);
    expect(html.match(/text-warn-ink/g)).toHaveLength(1);
    expect(html.match(/aria-hidden="true"><span class="absolute -inset-y/g)).toHaveLength(3);  // one bar per change
    expect(html).toContain(">Best<");
  });
  it("leaves out the mini bars with only two rows", () => {
    const html = draw([{ ...sectors, rows: sectors.rows.slice(0, 2) }]);
    expect(html).not.toContain("-inset-y-[3px]");
    expect(html).toContain("text-good");
  });
  it("shortens a big amount and keeps the full one in its title", () => {
    rememberLocale("en-US");
    const html = draw([{ type: "table", columns: ["Company", "Revenue"], rows: [["Acme", "$4,213,500,000"], ["Beta", "$812,000"]] }]);
    expect(html).toContain('title="$4,213,500,000"');
    expect(html).toContain(">$4.21B<");
  });
});
