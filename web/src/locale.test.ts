import { describe, expect, it } from "vitest";
import { rememberLocale, userLocale, usesLakhCrore } from "./locale";
import { fmt } from "./components/chartData";

describe("app locale", () => {
  it("follows what the server says, and lakh/crore only for India", () => {
    rememberLocale("en-US");
    expect(userLocale()).toBe("en-US");
    expect(usesLakhCrore()).toBe(false);
    expect(fmt(2500000)).toBe("2,500,000");
    rememberLocale("en-IN");
    expect(usesLakhCrore()).toBe(true);
    expect(fmt(2500000)).toBe("25.00L");
  });
  it("rupee amounts read in lakh/crore anywhere", () => {
    rememberLocale("en-US");
    expect(fmt(25000000, "₹")).toBe("₹2.50Cr");
    rememberLocale("en-IN");
  });
  it("ignores an empty locale", () => {
    rememberLocale("en-IN");
    rememberLocale("");
    expect(userLocale()).toBe("en-IN");
  });
});
