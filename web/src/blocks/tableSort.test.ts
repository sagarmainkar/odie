import { describe, expect, it } from "vitest";
import { cellNumber, isNumberColumn, nextSort, sortedOrder } from "./tableSort";

describe("table sorting", () => {
  it("reads the number a cell starts with", () => {
    expect(cellNumber("₹44,999")).toBe(44999);
    expect(cellNumber("4,800 mAh")).toBe(4800);
    expect(cellNumber("4.6★")).toBe(4.6);
    expect(cellNumber("Rs 500")).toBe(500);
    expect(cellNumber("-3%")).toBe(-3);
    expect(cellNumber("Pixel 10a")).toBeNull();
    expect(cellNumber(":badge[Best]{good}")).toBeNull();
    expect(cellNumber("")).toBeNull();
  });
  it("sorts numbers as numbers, text alphabetically, blanks last either way", () => {
    const rows = [["A", "₹300"], ["B", ""], ["C", "₹50"], ["D", "₹1,200"]];
    expect(sortedOrder(rows, { column: 1, direction: "up" })).toEqual([2, 0, 3, 1]);
    expect(sortedOrder(rows, { column: 1, direction: "down" })).toEqual([3, 0, 2, 1]);
    expect(sortedOrder([["Day 10"], ["Day 2"], ["day 1"]], { column: 0, direction: "up" })).toEqual([2, 1, 0]);
    expect(sortedOrder(rows, null)).toEqual([0, 1, 2, 3]);
  });
  it("cycles a header tap: up, down, back to the model's order", () => {
    const up = nextSort(null, 2);
    expect(up).toEqual({ column: 2, direction: "up" });
    const down = nextSort(up, 2);
    expect(down).toEqual({ column: 2, direction: "down" });
    expect(nextSort(down, 2)).toBeNull();
    expect(nextSort(down, 0)).toEqual({ column: 0, direction: "up" });
  });
  it("calls a column numeric when every filled cell starts with a number", () => {
    expect(isNumberColumn([["₹1"], [""], ["2 km"]], 0)).toBe(true);
    expect(isNumberColumn([["₹1"], ["Good"]], 0)).toBe(false);
    expect(isNumberColumn([[""]], 0)).toBe(false);
  });
});
