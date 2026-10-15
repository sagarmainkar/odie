import { describe, expect, it } from "vitest";
import { bankStyle, byDay, categoryIcon, money, vsLastMonth, type Txn } from "./money";

describe("money helpers", () => {
  it("formats rupees the Indian way", () => {
    expect(money(185300)).toBe("₹1,85,300");
    expect(money(899)).toBe("₹899");
    expect(money(19.99, "USD")).toBe("$19.99");
    expect(money(-2500)).toBe("-₹2,500");
  });
  it("gives each bank its badge", () => {
    expect(bankStyle("HDFC Bank").mono).toBe("HDFC");
    expect(bankStyle("State Bank of India").mono).toBe("SBI");
    expect(bankStyle("Saraswat Co-op Bank").mono).toBe("SARAS");
  });
  it("groups by day", () => {
    const t = (date: string): Txn => ({ date, direction: "debit", amount: 1, currency: "INR", counterparty: null, category: null });
    const g = byDay([t("2026-10-05"), t("2026-10-04"), t("2026-10-04"), t("2026-09-30")], "2026-10-05");
    expect(g.map((x) => [x.label, x.items.length])).toEqual([["Today", 1], ["Yesterday", 2], [g[2].label, 1]]);
    expect(g[2].label).toMatch(/30/);
  });
  it("compares with last month", () => {
    expect(vsLastMonth(1230, 1000)).toBe("▲ 23% vs last month");
    expect(vsLastMonth(500, 1000)).toBe("▼ 50% vs last month");
    expect(vsLastMonth(500, 0)).toBe("");
    expect(categoryIcon("groceries")).toBe("food");
    expect(categoryIcon(null)).toBe("rupee");
  });
});
