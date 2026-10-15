import { describe, expect, it } from "vitest";
import { rememberLocale } from "../locale";
import { fillValues, formatNumber, formatWithUnit, startingValues } from "./fenceValues";
import { parseBlocks } from "./parse";

const values = new Map([["p", 4000000], ["r", 8.5], ["n", 20], ["zero", 0]]);

describe("shared values in text", () => {
  it("fills {formula} placeholders with live values, grouped the Indian way", () => {
    expect(fillValues("EMI ₹{round(emi(p, r, n))} for {n} years", values)).toBe("EMI ₹34,713 for 20 years");
    expect(fillValues("Loan {p}", values)).toBe("Loan 40,00,000");
    expect(fillValues("Rate {r}%", values)).toBe("Rate 8.5%");
  });
  it("shows – for one that can't be worked out, and leaves non-formulas as written", () => {
    expect(fillValues("Per year {p / zero}", values)).toBe("Per year –");
    expect(fillValues("Ghost {q + 1}", values)).toBe("Ghost –");
    expect(fillValues("{hello there} and {a.b}", values)).toBe("{hello there} and {a.b}");
  });
  it("groups rupees the Indian way on any install, other numbers the user's way", () => {
    rememberLocale("en-US");
    try {
      expect(fillValues("₹{p} or {p}", values)).toBe("₹40,00,000 or 4,000,000");
    } finally {
      rememberLocale("en-IN");
    }
  });
  it("leaves a badge's colour alone", () => {
    expect(fillValues(":badge[{n} left]{warn}", values)).toBe(":badge[20 left]{warn}");
  });
  it("leaves text alone in a fence without values", () => {
    expect(fillValues("Costs {p}", new Map())).toBe("Costs {p}");
  });
  it("finds every input in the fence, inside containers too; the first of a repeated id wins", () => {
    const blocks = parseBlocks(JSON.stringify([
      { type: "section", title: "Loan", children: [{ type: "calculator", inputs: [{ id: "p", value: 5, max: 10 }], outputs: [] }] },
      { type: "calculator", inputs: [{ id: "p", value: 7, max: 10 }, { id: "n", value: 3, max: 10 }] },
    ]))!;
    expect(startingValues(blocks)).toEqual(new Map([["p", 5], ["n", 3]]));
  });
});

describe("numbers with units", () => {
  it("money like the kpis block, % stuck on, other units after a space", () => {
    expect(formatWithUnit(34712.9, "₹")).toBe("₹34,713");
    expect(formatWithUnit(4000000, "₹")).toBe("₹40,00,000");
    expect(formatWithUnit(8.5, "%")).toBe("8.5%");
    expect(formatWithUnit(20, "years")).toBe("20 years");
    expect(formatWithUnit(1, "years")).toBe("1 year");
    expect(formatWithUnit(1, "pts")).toBe("1 pts");
    expect(formatWithUnit(1234567, undefined)).toBe("12,34,567");
    expect(formatNumber(0.125)).toBe("0.13");
    expect(formatNumber(123.45)).toBe("123.5");
  });
});
