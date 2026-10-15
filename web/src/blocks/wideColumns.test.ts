import { describe, expect, it } from "vitest";
import { wideColumns } from "./wideColumns";

describe("wideColumns", () => {
  it("keeps two columns for one or two cards", () => {
    expect(wideColumns(1)).toBe("");
    expect(wideColumns(2)).toBe("");
  });
  it("puts three or four cards in one row", () => {
    expect(wideColumns(3)).toBe("@xl:grid-cols-3");
    expect(wideColumns(4)).toBe("@xl:grid-cols-4");
  });
  it("makes rows of three for more", () => {
    expect(wideColumns(5)).toBe("@xl:grid-cols-3");
    expect(wideColumns(6)).toBe("@xl:grid-cols-3");
  });
});
