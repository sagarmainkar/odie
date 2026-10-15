import { describe, expect, it } from "vitest";
import { plainMath } from "./plainMath";

describe("LaTeX symbols in replies", () => {
  it("turns symbol-only math into the characters", () => {
    expect(plainMath("Pune $\\rightarrow$ Goa")).toBe("Pune → Goa");
    expect(plainMath("Step 1 $\\to$ step 2 $\\Rightarrow$ done")).toBe("Step 1 → step 2 ⇒ done");
    expect(plainMath("$5 \\times 3 \\approx 15$")).toBe("5 × 3 ≈ 15");
    expect(plainMath("It's $27^\\circ$C and $\\leq 30\\%$")).toBe("It's 27°C and ≤ 30%");
    expect(plainMath("\\(a \\neq b\\)")).toBe("a ≠ b");
    expect(plainMath("$\\text{Check-in} \\rightarrow \\text{Check-out}$")).toBe("Check-in → Check-out");
  });
  it("leaves money and ordinary text alone", () => {
    expect(plainMath("Rooms from $120 to $200 a night")).toBe("Rooms from $120 to $200 a night");
    expect(plainMath("Costs $5 and $10")).toBe("Costs $5 and $10");
    expect(plainMath("a path like C:\\Users\\me")).toBe("a path like C:\\Users\\me");
  });
  it("keeps real formulas it can't turn into plain text, and code untouched", () => {
    expect(plainMath("$\\frac{a}{b}$")).toBe("$\\frac{a}{b}$");
    expect(plainMath("`$\\rightarrow$` and ```\n$\\to$\n```")).toBe("`$\\rightarrow$` and ```\n$\\to$\n```");
  });
  it("handles a bare command outside dollars too", () => {
    expect(plainMath("Mumbai \\rightarrow Pune")).toBe("Mumbai → Pune");
    expect(plainMath("Pune $\\\\rightarrow$ Goa")).toBe("Pune → Goa");  // a doubled backslash, as models sometimes write
  });
});
